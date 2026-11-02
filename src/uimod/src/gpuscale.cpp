// uimod GPU present for the stretched display modes (Windowed, letterboxed Borderless).
//
// The game re-presents its whole frame on every mouse move while a unit move path is drawn. At a
// 3840x2160 backbuffer no CPU resampler keeps up with that, so the scaling moves to the GPU:
//
//   * the 8-bit frame lives in an R8 texture; each flip uploads only its dirty rect,
//   * the 256-colour table the game would have blitted with goes into a 256x1 texture per flip,
//   * one pixel shader draws the client area: per output pixel it walks the source texels under
//     the pixel's footprint, looks each up in the palette and weights it by its overlap --
//     area-average when shrinking, bilinear when enlarging. That is the CPU resampler's law
//     (vidmode.cpp ScaledFlip), so the two paths produce the same picture.
//
// Filtering happens AFTER the palette lookup (indices cannot be interpolated), which is why this is a
// shader and not a sampler state.
//
// The same shader composites the lines the engine draws onto the window itself (the tutorial pointer:
// lineoverlay.h, fed by vidmode.cpp), in client space, minus the parts a later flip repainted away.
//
// The swap chain is the blt model (DXGI_SWAP_EFFECT_DISCARD) on the game window itself: GDI drawing to
// the same window keeps working (the movie player BitBlts there), which a flip-model chain would hide.
// DISCARD leaves the back buffer undefined after Present, so every flip draws the whole client -- a few
// hundred microseconds of GPU time. Present(0): never wait for vblank, the game flips many times a frame.
// DXGI's own Alt+Enter handling is switched off (PRACX and vidmode own that key).
//
// Nothing here is linked statically: d3d11.dll and d3dcompiler_47.dll are loaded on first use, and any
// failure (no DLL, no device) turns the path off for the session and the CPU resampler takes over. The
// module knows nothing about PRACX.
//
// The device (and its swap chain) is made on a worker thread; the game thread keeps presenting through the
// CPU resampler until it is ready. Device creation waits on the driver, and during a GPU reset that wait has
// no bound -- on the game thread it froze the game with the pointer clipped (2026-10-24). Nothing here
// touches the GPU within vidsafety::kGpuQuietMs of a display event (no creation, resize, upload or present:
// the CPU path draws meanwhile), and a device lost to a driver reset is released and made again after a growing
// back-off (2 s, 10 s, then every 60 s; vidsafety::GpuLife), never sooner than that quiet.

#include "gpuscale.h"
#include "lineoverlay.h"
#include "vidsafety.h"

#include <d3d11.h>
#include <d3dcompiler.h>
#include <cstdio>
#include <cstring>

void UimodLog(const char* msg);

namespace {

const char kShader[] = R"(
Texture2D<float>  Frame : register(t0);
Texture2D<float4> Pal   : register(t1);
cbuffer C : register(b0) { float2 srcSize; float2 dstSize; };
cbuffer L : register(b1)
{
    float4 lineHdr;          // x = line count, y = client pixels per frame pixel
    float4 lineSeg[8];       // client space: MoveTo x, y, LineTo x, y
    float4 lineSty[8];       // half width (client px), palette index, dash style (0 = solid), erase-rect count
    float4 lineErase[48];    // client space, half-open l t r b; 6 per line
};

// GDI's cosmetic dash patterns, in frame pixels from the MoveTo point (1 dash, 2 dot, 3 dash-dot, 4 dash-dot-dot)
bool DashOn(int st, float s)
{
    if (st == 2) return fmod(s, 6.0) < 3.0;
    float m = fmod(s, 24.0);
    if (st == 1) return m < 18.0;
    if (st == 3) return m < 9.0 || (m >= 15.0 && m < 18.0);
    return m < 9.0 || (m >= 12.0 && m < 15.0) || (m >= 18.0 && m < 21.0);
}

float3 Lines(float2 p, float3 col)
{
    int nl = (int)lineHdr.x;
    [loop] for (int li = 0; li < nl; ++li) {
        float2 a = lineSeg[li].xy;
        float2 ab = lineSeg[li].zw - a;
        float len2 = dot(ab, ab);
        float t = len2 > 0.0 ? saturate(dot(p - a, ab) / len2) : 0.0;
        float cov = saturate(lineSty[li].x + 0.5 - length(p - (a + t * ab)));
        if (cov <= 0.0) continue;
        int st = (int)lineSty[li].z;
        if (st != 0 && !DashOn(st, t * sqrt(len2) / lineHdr.y)) continue;
        bool hidden = false;
        int ne = (int)lineSty[li].w;
        [loop] for (int k = 0; k < ne; ++k) {
            float4 e = lineErase[li * 6 + k];
            hidden = hidden || (p.x >= e.x && p.x < e.z && p.y >= e.y && p.y < e.w);
        }
        if (hidden) continue;
        col = lerp(col, Pal.Load(int3((int)lineSty[li].y, 0, 0)).rgb, cov);
    }
    return col;
}

float4 vs(uint id : SV_VertexID) : SV_Position
{
    return float4((id == 1) ? 3.0 : -1.0, (id == 2) ? -3.0 : 1.0, 0.0, 1.0);
}

float4 ps(float4 pos : SV_Position) : SV_Target
{
    float2 scale = srcSize / dstSize;
    float2 foot = max(scale, 1.0);                 // the output pixel's footprint in source pixels (>= 1: bilinear)
    float2 centre = pos.xy * scale;
    float2 lo = centre - 0.5 * foot, hi = centre + 0.5 * foot;
    int2 base = (int2)floor(lo);
    int2 n = (int2)ceil(hi) - base;
    int2 last = (int2)srcSize - 1;
    float3 acc = 0;
    [loop] for (int j = 0; j < n.y; ++j) {
        float ty = base.y + j;
        float wy = max(0.0, min(ty + 1.0, hi.y) - max(ty, lo.y));
        [loop] for (int i = 0; i < n.x; ++i) {
            float tx = base.x + i;
            float wx = max(0.0, min(tx + 1.0, hi.x) - max(tx, lo.x));
            int2 tc = clamp(int2(tx, ty), int2(0, 0), last);
            int idx = (int)(Frame.Load(int3(tc, 0)) * 255.0 + 0.5);
            acc += wx * wy * Pal.Load(int3(idx, 0, 0)).rgb;
        }
    }
    return float4(Lines(pos.xy, acc / (foot.x * foot.y)), 1.0);
}
)";

struct CB { float srcW, srcH, dstW, dstH; };
struct LineCB {                                    // cbuffer L, register b1
    float hdr[4];
    float seg[lineoverlay::kMaxLines][4];
    float sty[lineoverlay::kMaxLines][4];
    float erase[lineoverlay::kMaxLines * lineoverlay::kMaxErase][4];
};
static_assert(lineoverlay::kMaxLines == 8 && lineoverlay::kMaxErase == 6, "the shader's cbuffer L is sized 8 x 6");
static_assert(sizeof(LineCB) % 16 == 0, "constant buffers are float4 rows");

bool g_failed = false;               // the GPU path is off for the session (g_life.st == kOff)
bool g_stale = true;
vidsafety::GpuLife g_life;
volatile LONG g_dispTick = 0;        // GetTickCount of the last display event (either thread)
volatile LONG g_dispSeen = 0;        // there was one
HWND g_hwnd = nullptr;
int  g_sw = 0, g_sh = 0, g_cw = 0, g_ch = 0;

ID3D11Device*             g_dev = nullptr;
ID3D11DeviceContext*      g_ctx = nullptr;
IDXGISwapChain*           g_swap = nullptr;
ID3D11RenderTargetView*   g_rtv = nullptr;
ID3D11Texture2D*          g_frame = nullptr;
ID3D11ShaderResourceView* g_frameSrv = nullptr;
ID3D11Texture2D*          g_pal = nullptr;
ID3D11ShaderResourceView* g_palSrv = nullptr;
ID3D11Buffer*             g_cb = nullptr;
ID3D11Buffer*             g_lineCb = nullptr;
ID3D11VertexShader*       g_vs = nullptr;
ID3D11PixelShader*        g_ps = nullptr;

lineoverlay::Line g_lines[lineoverlay::kMaxLines];   // frame space, from GpuSetLines
int g_lineCount = 0;

template <typename T> void Release(T*& p) { if (p) { p->Release(); p = nullptr; } }

void ReleaseAll()
{
    if (g_ctx) g_ctx->ClearState();
    Release(g_rtv); Release(g_frameSrv); Release(g_frame); Release(g_palSrv); Release(g_pal);
    Release(g_cb); Release(g_lineCb); Release(g_vs); Release(g_ps); Release(g_swap); Release(g_ctx); Release(g_dev);
    g_hwnd = nullptr; g_sw = g_sh = g_cw = g_ch = 0;
}

bool Fail(const char* what, HRESULT hr)
{
    char msg[160];
    _snprintf_s(msg, sizeof msg, _TRUNCATE, "[uimod] gpuscale: %s failed (0x%08lX) -> CPU scaler for this session\n",
                what, static_cast<unsigned long>(hr));
    UimodLog(msg);
    ReleaseAll();
    g_failed = true;
    g_life.Failed();
    return false;
}

// A call on the live device failed: a driver reset / removal releases the device; a new one after the back-off and
// the display's quiet (a removal counts as a display event). Anything else is Fail.
bool Lost(const char* what, HRESULT hr)
{
    const HRESULT why = g_dev ? g_dev->GetDeviceRemovedReason() : S_OK;
    const HRESULT code = vidsafety::DeviceLost(static_cast<long>(hr)) ? hr : why;
    if (!g_life.Lost(static_cast<long>(code), GetTickCount())) return Fail(what, hr);
    char msg[220];
    _snprintf_s(msg, sizeof msg, _TRUNCATE,
                "[uimod] gpuscale: %s: device lost (0x%08lX, reason 0x%08lX) -> released, CPU scaler; a new device in %u s\n",
                what, static_cast<unsigned long>(hr), static_cast<unsigned long>(why),
                static_cast<unsigned>(vidsafety::GpuBackoffMs(g_life.losses) / 1000));
    UimodLog(msg);
    ReleaseAll();
    return false;
}

bool MakeTarget()
{
    ID3D11Texture2D* back = nullptr;
    HRESULT hr = g_swap->GetBuffer(0, __uuidof(ID3D11Texture2D), reinterpret_cast<void**>(&back));
    if (FAILED(hr)) return Fail("GetBuffer", hr);
    hr = g_dev->CreateRenderTargetView(back, nullptr, &g_rtv);
    back->Release();
    return FAILED(hr) ? Fail("CreateRenderTargetView", hr) : true;
}

// What the worker makes -- the device, its swap chain on the game window, the shaders and the small resources --
// and hands to the game thread, which owns all of it from then on. A D3D11 device is free-threaded; its immediate
// context is used by the game thread only, after the hand-over. The game thread never waits for the worker.
struct Made {
    HWND hwnd = nullptr; int cw = 0, ch = 0;            // in
    ID3D11Device* dev = nullptr; ID3D11DeviceContext* ctx = nullptr; IDXGISwapChain* swap = nullptr;
    ID3D11VertexShader* vs = nullptr; ID3D11PixelShader* ps = nullptr;
    ID3D11Texture2D* pal = nullptr; ID3D11ShaderResourceView* palSrv = nullptr;
    ID3D11Buffer* cb = nullptr; ID3D11Buffer* lineCb = nullptr;
    D3D_FEATURE_LEVEL got = D3D_FEATURE_LEVEL_10_0;
    const char* what = nullptr; HRESULT hr = S_OK;     // the failing step
    void Drop()
    {
        if (ctx) ctx->ClearState();
        Release(lineCb); Release(cb); Release(palSrv); Release(pal); Release(ps); Release(vs);
        Release(swap); Release(ctx); Release(dev);
    }
    bool Err(const char* w, HRESULT h) { what = w; hr = h; Drop(); return false; }
};

Made g_made;
volatile LONG g_madeDone = 0;          // the worker is finished with g_made
DWORD g_madeStart = 0;
bool g_madeWarned = false;

// The worker thread's whole job (the old game-thread CreateDevice, unchanged in what it creates).
bool MakeDevice(Made& m)
{
    const HMODULE d3d = LoadLibraryA("d3d11.dll");
    if (!d3d) return m.Err("loading d3d11.dll (Windows 7 SP1+ has it)", HRESULT_FROM_WIN32(GetLastError()));
    // The shader is compiled at run time. Windows 8+ ship d3dcompiler_47; Windows 7 has it only through KB4019990
    // (the .NET 4.7 prerequisite, 2017) -- but the June 2010 DirectX redistributable that most games install left
    // d3dcompiler_43 behind, and vs_4_0/ps_4_0 compile the same there. Neither -> the CPU scaler, named.
    HMODULE comp = LoadLibraryA("d3dcompiler_47.dll");
    if (!comp) comp = LoadLibraryA("d3dcompiler_43.dll");
    if (!comp) return m.Err("loading d3dcompiler_47.dll / d3dcompiler_43.dll (Windows 7: install KB4019990 or the DirectX June 2010 redist)",
                            HRESULT_FROM_WIN32(GetLastError()));
    using FCreate = HRESULT(WINAPI*)(IDXGIAdapter*, D3D_DRIVER_TYPE, HMODULE, UINT, const D3D_FEATURE_LEVEL*, UINT, UINT,
                                     const DXGI_SWAP_CHAIN_DESC*, IDXGISwapChain**, ID3D11Device**, D3D_FEATURE_LEVEL*,
                                     ID3D11DeviceContext**);
    using FCompile = HRESULT(WINAPI*)(LPCVOID, SIZE_T, LPCSTR, const D3D_SHADER_MACRO*, ID3DInclude*, LPCSTR, LPCSTR,
                                      UINT, UINT, ID3DBlob**, ID3DBlob**);
    const auto create = reinterpret_cast<FCreate>(GetProcAddress(d3d, "D3D11CreateDeviceAndSwapChain"));
    const auto compile = reinterpret_cast<FCompile>(GetProcAddress(comp, "D3DCompile"));
    if (!create || !compile) return m.Err("resolving D3D entry points", E_NOINTERFACE);

    DXGI_SWAP_CHAIN_DESC sd = {};
    sd.BufferDesc.Width = static_cast<UINT>(m.cw);
    sd.BufferDesc.Height = static_cast<UINT>(m.ch);
    sd.BufferDesc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    sd.SampleDesc.Count = 1;
    sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    sd.BufferCount = 1;
    sd.OutputWindow = m.hwnd;
    sd.Windowed = TRUE;
    sd.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
    const D3D_FEATURE_LEVEL want[] = { D3D_FEATURE_LEVEL_11_0, D3D_FEATURE_LEVEL_10_1, D3D_FEATURE_LEVEL_10_0 };
    HRESULT hr = create(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, want, 3, D3D11_SDK_VERSION, &sd, &m.swap, &m.dev,
                        &m.got, &m.ctx);
    if (FAILED(hr)) return m.Err("D3D11CreateDeviceAndSwapChain", hr);

    IDXGIFactory* factory = nullptr;
    if (SUCCEEDED(m.swap->GetParent(__uuidof(IDXGIFactory), reinterpret_cast<void**>(&factory)))) {
        factory->MakeWindowAssociation(m.hwnd, DXGI_MWA_NO_WINDOW_CHANGES | DXGI_MWA_NO_ALT_ENTER);
        factory->Release();
    }

    ID3DBlob* blob = nullptr;
    ID3DBlob* err = nullptr;
    hr = compile(kShader, sizeof kShader - 1, "uimod_gpuscale", nullptr, nullptr, "vs", "vs_4_0", 0, 0, &blob, &err);
    if (err) err->Release();
    if (FAILED(hr)) return m.Err("compiling the vertex shader", hr);
    hr = m.dev->CreateVertexShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, &m.vs);
    blob->Release();
    if (FAILED(hr)) return m.Err("CreateVertexShader", hr);
    err = nullptr;
    hr = compile(kShader, sizeof kShader - 1, "uimod_gpuscale", nullptr, nullptr, "ps", "ps_4_0", 0, 0, &blob, &err);
    if (err) err->Release();
    if (FAILED(hr)) return m.Err("compiling the pixel shader", hr);
    hr = m.dev->CreatePixelShader(blob->GetBufferPointer(), blob->GetBufferSize(), nullptr, &m.ps);
    blob->Release();
    if (FAILED(hr)) return m.Err("CreatePixelShader", hr);

    D3D11_TEXTURE2D_DESC td = {};
    td.Width = 256; td.Height = 1; td.MipLevels = 1; td.ArraySize = 1;
    td.Format = DXGI_FORMAT_B8G8R8X8_UNORM;        // RGBQUAD's byte order
    td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_DEFAULT;
    td.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    hr = m.dev->CreateTexture2D(&td, nullptr, &m.pal);
    if (SUCCEEDED(hr)) hr = m.dev->CreateShaderResourceView(m.pal, nullptr, &m.palSrv);
    if (FAILED(hr)) return m.Err("creating the palette texture", hr);

    D3D11_BUFFER_DESC bd = {};
    bd.ByteWidth = sizeof(CB);
    bd.Usage = D3D11_USAGE_DEFAULT;
    bd.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    hr = m.dev->CreateBuffer(&bd, nullptr, &m.cb);
    if (FAILED(hr)) return m.Err("creating the constant buffer", hr);
    bd.ByteWidth = sizeof(LineCB);
    hr = m.dev->CreateBuffer(&bd, nullptr, &m.lineCb);
    if (FAILED(hr)) return m.Err("creating the line constant buffer", hr);
    return true;
}

DWORD WINAPI MakeDeviceThread(LPVOID)
{
    MakeDevice(g_made);
    InterlockedExchange(&g_madeDone, 1);
    return 0;
}

// The game thread: true = a device is up. Otherwise it starts the worker (when the display has been quiet long
// enough), or adopts what the worker finished, and the caller presents on the CPU meanwhile. Never waits.
bool EnsureDevice(HWND hwnd, int cw, int ch)
{
    if (g_dev) return true;
    const DWORD now = GetTickCount();
    if (g_life.st == vidsafety::GpuLife::kIdle) {
        if (!g_life.MayStart(now)) return false;
        g_made = Made();
        g_made.hwnd = hwnd; g_made.cw = cw; g_made.ch = ch;
        g_madeDone = 0;
        g_madeStart = now;
        g_madeWarned = false;
        const HANDLE th = CreateThread(nullptr, 256 * 1024, MakeDeviceThread, nullptr, 0, nullptr);
        if (!th) return Fail("starting the device thread", HRESULT_FROM_WIN32(GetLastError()));
        CloseHandle(th);
        g_life.Started();
        UimodLog("[uimod] gpuscale: making the D3D11 device on a worker thread (CPU scaler until it is ready)\n");
        return false;
    }
    if (g_life.st != vidsafety::GpuLife::kCreating) return false;
    if (!g_madeDone) {
        if (!g_madeWarned && vidsafety::Since(now, g_madeStart) >= vidsafety::kGpuCreateWarnMs) {
            g_madeWarned = true;
            UimodLog("[uimod] gpuscale: device creation still waiting on the driver after 10 s -> CPU scaler meanwhile\n");
        }
        return false;
    }
    Made m = g_made;
    g_made = Made();
    if (m.what) {
        g_life.Created(false, now);
        if (g_life.st == vidsafety::GpuLife::kOff) return Fail(m.what, m.hr);
        char msg[200];                   // after a device loss: the driver may still be recovering -- later again
        _snprintf_s(msg, sizeof msg, _TRUNCATE, "[uimod] gpuscale: %s failed (0x%08lX) after a device loss -> CPU scaler, "
                    "next try in %u s\n", m.what, static_cast<unsigned long>(m.hr),
                    static_cast<unsigned>(vidsafety::GpuBackoffMs(g_life.losses) / 1000));
        UimodLog(msg);
        return false;
    }
    if (m.hwnd != hwnd || !g_life.Settled(now)) {   // another window by now, or a display event meanwhile: again later
        m.Drop();
        g_life.st = vidsafety::GpuLife::kIdle;
        UimodLog("[uimod] gpuscale: the new device is out of date (window or display changed) -> made again later\n");
        return false;
    }
    g_dev = m.dev; g_ctx = m.ctx; g_swap = m.swap; g_vs = m.vs; g_ps = m.ps;
    g_pal = m.pal; g_palSrv = m.palSrv; g_cb = m.cb; g_lineCb = m.lineCb;
    g_hwnd = hwnd; g_cw = m.cw; g_ch = m.ch;
    if (!MakeTarget()) return false;
    g_life.Created(true, now);
    g_stale = true;
    char msg[96];
    _snprintf_s(msg, sizeof msg, _TRUNCATE, "[uimod] gpuscale: D3D11 present up (feature level 0x%X)\n", static_cast<unsigned>(m.got));
    UimodLog(msg);
    return true;
}

// Display events from either thread (GpuDisplayEvent), into the game thread's GpuLife.
void FeedDisplayEvents()
{
    if (g_dispSeen) g_life.DisplayEvent(static_cast<uint32_t>(g_dispTick));
}

bool EnsureFrameTexture(int sw, int sh)
{
    if (g_frame && sw == g_sw && sh == g_sh) return true;
    Release(g_frameSrv); Release(g_frame);
    D3D11_TEXTURE2D_DESC td = {};
    td.Width = static_cast<UINT>(sw); td.Height = static_cast<UINT>(sh); td.MipLevels = 1; td.ArraySize = 1;
    td.Format = DXGI_FORMAT_R8_UNORM;
    td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_DEFAULT;
    td.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    HRESULT hr = g_dev->CreateTexture2D(&td, nullptr, &g_frame);
    if (SUCCEEDED(hr)) hr = g_dev->CreateShaderResourceView(g_frame, nullptr, &g_frameSrv);
    if (FAILED(hr)) return Fail("creating the frame texture", hr);
    g_sw = sw; g_sh = sh;
    g_stale = true;
    return true;
}

// The lines in client space for cbuffer L: centres of frame pixels map to the images of those centres (the frame
// shader's own mapping), the pen and the erase rects scale with the frame.
void FillLineCB(LineCB& L)
{
    memset(&L, 0, sizeof L);
    const float sx = static_cast<float>(g_cw) / static_cast<float>(g_sw);
    const float sy = static_cast<float>(g_ch) / static_cast<float>(g_sh);
    const float s = 0.5f * (sx + sy);              // uniform: the display modes keep the frame's aspect
    L.hdr[0] = static_cast<float>(g_lineCount);
    L.hdr[1] = s;
    for (int i = 0; i < g_lineCount; ++i) {
        const lineoverlay::Line& l = g_lines[i];
        L.seg[i][0] = (l.x0 + 0.5f) * sx; L.seg[i][1] = (l.y0 + 0.5f) * sy;
        L.seg[i][2] = (l.x1 + 0.5f) * sx; L.seg[i][3] = (l.y1 + 0.5f) * sy;
        L.sty[i][0] = 0.5f * static_cast<float>(lineoverlay::PenWidth(l)) * s;
        L.sty[i][1] = static_cast<float>(l.color & 0xFF);
        L.sty[i][2] = lineoverlay::Dashed(l) ? static_cast<float>(lineoverlay::StyleOf(l.style)) : 0.0f;
        L.sty[i][3] = static_cast<float>(l.nErase);
        for (int k = 0; k < l.nErase; ++k) {
            float* e = L.erase[i * lineoverlay::kMaxErase + k];
            e[0] = l.erase[k].l * sx; e[1] = l.erase[k].t * sy; e[2] = l.erase[k].r * sx; e[3] = l.erase[k].b * sy;
        }
    }
}

// The whole client from the frame texture (+ the lines), then Present: DISCARD leaves nothing of the last one.
bool DrawPresent()
{
    LineCB L;
    FillLineCB(L);
    g_ctx->UpdateSubresource(g_lineCb, 0, nullptr, &L, 0, 0);
    const D3D11_VIEWPORT vp = { 0.0f, 0.0f, static_cast<float>(g_cw), static_cast<float>(g_ch), 0.0f, 1.0f };
    g_ctx->RSSetViewports(1, &vp);
    g_ctx->OMSetRenderTargets(1, &g_rtv, nullptr);
    g_ctx->IASetInputLayout(nullptr);
    g_ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    g_ctx->VSSetShader(g_vs, nullptr, 0);
    g_ctx->PSSetShader(g_ps, nullptr, 0);
    ID3D11Buffer* cbs[2] = { g_cb, g_lineCb };
    g_ctx->PSSetConstantBuffers(0, 2, cbs);
    ID3D11ShaderResourceView* srv[2] = { g_frameSrv, g_palSrv };
    g_ctx->PSSetShaderResources(0, 2, srv);
    g_ctx->Draw(3, 0);

    const HRESULT hr = g_swap->Present(0, 0);
    if (FAILED(hr)) return Lost("Present", hr);
    g_life.Presented(GetTickCount());
    return true;
}

} // namespace

void GpuInvalidate() { g_stale = true; }

void GpuSetLines(const lineoverlay::Line* lines, int n)
{
    if (n < 0) n = 0;
    if (n > lineoverlay::kMaxLines) n = lineoverlay::kMaxLines;
    for (int i = 0; i < n; ++i) g_lines[i] = lines[i];
    g_lineCount = n;
}

void GpuDisplayEvent()
{
    InterlockedExchange(&g_dispTick, static_cast<LONG>(GetTickCount()));
    InterlockedExchange(&g_dispSeen, 1);
}

bool GpuCurrent(HWND hwnd, int cw, int ch)
{
    FeedDisplayEvents();
    if (!g_life.MayUse(GetTickCount())) return false;   // a display event just now: nothing goes to the GPU
    return !g_failed && g_dev && g_frame && !g_stale && hwnd == g_hwnd && cw == g_cw && ch == g_ch;
}

bool GpuRepresent(HWND hwnd, int cw, int ch)
{
    return GpuCurrent(hwnd, cw, ch) && DrawPresent();
}

bool GpuPresent(HWND hwnd, const BYTE* bits, int stride, int sw, int sh, const RGBQUAD* pal,
                int l, int t, int r, int b, int cw, int ch)
{
    if (g_failed || !hwnd || !bits || sw <= 0 || sh <= 0 || cw <= 0 || ch <= 0) return false;
    FeedDisplayEvents();
    // within kGpuQuietMs of a display event the GPU is not touched at all (the driver may be resetting): CPU path,
    // and the caller marks the frame copy stale
    if (!g_life.MayUse(GetTickCount())) return false;
    if (g_dev && hwnd != g_hwnd) { ReleaseAll(); g_life.st = vidsafety::GpuLife::kIdle; }
    if (!EnsureDevice(hwnd, cw, ch)) return false;
    if (cw != g_cw || ch != g_ch) {
        g_ctx->OMSetRenderTargets(0, nullptr, nullptr);
        Release(g_rtv);
        const HRESULT hr = g_swap->ResizeBuffers(1, static_cast<UINT>(cw), static_cast<UINT>(ch), DXGI_FORMAT_UNKNOWN, 0);
        if (FAILED(hr)) return Lost("ResizeBuffers", hr);
        g_cw = cw; g_ch = ch;
        if (!MakeTarget()) return false;
    }
    if (!EnsureFrameTexture(sw, sh)) return false;

    if (g_stale) { l = 0; t = 0; r = sw; b = sh; g_stale = false; }
    if (l < 0) l = 0;
    if (t < 0) t = 0;
    if (r > sw) r = sw;
    if (b > sh) b = sh;
    if (l < r && t < b) {
        const D3D11_BOX box = { static_cast<UINT>(l), static_cast<UINT>(t), 0, static_cast<UINT>(r), static_cast<UINT>(b), 1 };
        g_ctx->UpdateSubresource(g_frame, 0, &box, bits + static_cast<size_t>(t) * stride + l, static_cast<UINT>(stride), 0);
    }
    g_ctx->UpdateSubresource(g_pal, 0, nullptr, pal, 256 * 4, 0);
    const CB cb = { static_cast<float>(sw), static_cast<float>(sh), static_cast<float>(cw), static_cast<float>(ch) };
    g_ctx->UpdateSubresource(g_cb, 0, nullptr, &cb, 0, 0);
    return DrawPresent();
}
