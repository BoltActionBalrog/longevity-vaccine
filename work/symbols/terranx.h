// SMACX terranx.exe symbol table — our running record.
//
// Binary: MD5 2d0b1438eb73f98519134d7a4f6bc054 (PRACX-patched GOG build,
// 2024-08-19). Image base 0x00400000. Addresses do NOT match an unpatched
// binary, the 1999 build, or other distributions.
//
// SYMBOLS ONLY. No narrative/rationale/status — that lives in project memory
// and work/patches/*.yaml. This file holds three machine-parseable line shapes:
//
//   1. Function:  extern <ret> <name>(<args>);   // addr: 0xADDR  <origin>  <note>
//   2. Global:    extern <type> <name>;          // addr: 0xADDR  <origin>  <note>
//   3. Field:     // field: <Struct> +0xOFF <type> <name>   <note>
//
// Parse rule for symbols (shapes 1-2): match a line beginning `extern`, take the
// declared identifier (the last identifier before `(` or `;`) as the name, and
// the `0xADDR` after `addr:` as the address. `()` means args unknown.
// <origin> = thinker | observed | guess. `;`-comments after a field/decl are notes.
//
// Calling convention & callee-cleanup (RET imm) are recorded in the trailing
// note where known (thiscall = `this` in ECX). Types are forward-declared opaque.

#pragma once
#include <stdint.h>

struct Buffer;
struct Sprite;
struct Palette;
struct Font;
struct GraphicWin;
struct BasePop;
struct CWorldbuilder;
typedef struct _RECT { int32_t left, top, right, bottom; } RECT;


// ============================================================================
// PCX atlas + sprite-extract primitives
// ============================================================================
extern int  Buffer_load_pcx(struct Buffer* self, const char* filename, struct Palette* pal, int a4, int len);   // addr: 0x005D7DE0  thinker  thiscall; decode PCX file into Buffer
extern int  Buffer_load_pcx_2(struct Buffer* self, uint8_t* data, uint32_t a3, struct Palette* pal, int len, int a6); // addr: 0x005E2690  thinker  thiscall; decode PCX from memory
extern int  Buffer_change_color(struct Buffer* self, int from, int to);                                         // addr: 0x005DE580  thinker  thiscall
extern int  Buffer_change_color_2(struct Buffer* self, RECT* region, int from, int to);                         // addr: 0x005DE730  thinker  thiscall
extern int  Buffer_change_color_3(struct Buffer* self, int a2, int a3, int a4, int a5, int a6, int a7);         // addr: 0x005E2070  thinker  thiscall
extern int  Sprite_extract(struct Sprite* self, struct Buffer* src, int a3, RECT* region, void* a5);            // addr: 0x005E3960  thinker  thiscall
extern int  Sprite_extract_2(struct Sprite* self, struct Buffer* src, int a3, int x, int y, int w, int h, void* a8); // addr: 0x005E39A0  thinker  thiscall; (x,y,w,h) are the hard-coded UI atlas literals
extern void Sprite_close(struct Sprite* self);  // addr: 0x005E3820  thinker  thiscall; frees +0x04 only when +0x28 == 0

// ============================================================================
// UI asset loaders (one per PCX; call Buffer_load_pcx then Sprite_extract_2 x N)
// ============================================================================
extern void load_interface(int a1);          // addr: 0x00455610  thinker   loads iface.pcx + interface.pcx (main HUD atlas); sets caption_draw_callback
extern void def_caption_draw(void);           // addr: 0x004554C0  thinker   caption/label draw helper (installed into caption_draw_callback)
extern void load_icons(void);                 // addr: 0x004547E0  thinker   ICONS.PCX + NEWICONS.PCX
extern void load_cursors(void);               // addr: 0x00454FC0  thinker   12 cursor sprites cut from CURSOR.PCX; skips while g_cursor_cut_guard != 0
extern struct Sprite g_cursor_sprites[12];     // addr: 0x0093AA70  observed  load_cursors' sprites, stride 0x2C (1 go-to target, 5 invalid, 8 patrol)
extern int  g_cursor_hot_x[12];                // addr: 0x0093AA10  observed  hotspot x per cursor sprite (palette-5 marker pixel)
extern int  g_cursor_hot_y[12];                // addr: 0x0093AA40  observed  hotspot y per cursor sprite
extern int  g_cursor_cut_guard;                // addr: 0x009BC494  observed  load_cursors returns at once while non-zero
extern void load_fixed_sprites(void);         // addr: 0x00455E80  thinker   parent UI bootstrap; sole caller of load_interface
extern void load_menu(void);                  // addr: 0x00402F40  guess     menu.pcx (main menu)
extern void load_faction_art(int faction);    // addr: 0x00453710  thinker   cdecl; <faction>.pcx -> 37 Sprites at g_faction_sprites[faction]
extern void load_terrain(void);                // addr: 0x00451C50  thinker   TER1.PCX / TER1WRECK.PCX / TEXTURE.PCX -> the terrain sprites and textures
extern void load_vehicles(void);               // addr: 0x00454270  thinker   UNITS.PCX -> the unit sprites
extern void show_credits(void);               // addr: 0x00428DF0  thinker   View Credits entry: new CreditsWin(0x2D6C) + load_credits_a; callers top_menu/Console_menu_proc/Console_on_key_click/end_of_game
extern void CreditsWin_ctor(void* self);      // addr: 0x00428780  observed  thiscall; 2x GraphicWin + Font + Buffer + FlatButton + Time subobjects
extern void load_credits_a(struct CreditsWin* self); // addr: 0x004289F0  observed  thiscall; View Credits modal: fullscreen win + credits[2].pcx via GraphicWin_load_pcx + 400x400 scroller subwin @(30,200|100) + Font 14 + 30ms timer
extern void credits_load_text(struct CreditsWin* self); // addr: 0x00428880  observed  thiscall; reads CREDITS text section into lines[512] @+0xA1C, tracks max Font_width @+0x1230
extern void credits_draw(struct CreditsWin* self); // addr: 0x00428C00  observed  fastcall; per-tick scroller draw: fill(9) + centred lines offset by +0xA14 + 8x2px fade bands + composite
extern void credits_tick(struct CreditsWin* self); // addr: 0x00428DD0  observed  cdecl timer cb (0x616350, 30ms): ++[+0xA14]; credits_draw
extern void load_credits_b(struct InterludeWin* self, char* section); // addr: 0x0045F2E0  observed  thiscall RET 4; INTERLUDE screen: fullscreen win + credits[2].pcx via Buffer_load_pcx into +0xA54 + wrapped text block (rect from +0x474 client, 1/6 insets, L clamp 0x19, INTERLUDE21/22 +0x32)
extern void interlude(int event_id, const char* text, int a3, int a4); // addr: 0x005230E0  thinker  cdecl; story-event screen -> load_credits_b @0x52398F
// field: CreditsWin +0xA14 int tick_counter        scroll offset source (1/tick native)
// field: CreditsWin +0xA18 int line_count
// field: CreditsWin +0xA1C char* lines[512]        CREDITS text lines (mem_get'd)
// field: CreditsWin +0x122C int line_height        from Font fields after Font_init
// field: CreditsWin +0x1230 int max_line_width
// field: CreditsWin +0x1234 struct GraphicWin subwin   the 400x400 scroller window
// field: CreditsWin +0x1C48 struct Font font       "Alpha Centauri" size 14; measures AND draws
// field: InterludeWin +0xA14 RECT text_rect
// field: InterludeWin +0xA24 void* text_list       built by 0x608980 from INTERLUDEX/INTERLUDEA section
// field: InterludeWin +0xA54 struct Buffer backdrop_buf  credits[2].pcx target; composited 1:1
extern int  load_hoficons(void);              // addr: 0x00448400  observed  fastcall(this=FameWin); builds HOF window (frame/hof/hoficons.pcx; 800x600 logical, 1024x768 window at wide)
extern int  load_monicons(/*ecx*/ struct GraphicWin* self); // addr: 0x00472230  thinker  fastcall(this=MonumentWin_g); builds the whole Monument screen (monument.flc + monzoom1/2 + monicons.pcx); ret 0 = ok
extern void init_report_screen(void);         // addr: 0x004A3460  observed  report.pcx + report-page layout; 800/1024 res-conditional

// ============================================================================
// Resolution globals (PRACX writes these from Alpha Centauri.Ini at startup)
// ============================================================================
extern int* ScreenWidth;                      // addr: 0x009B7B1C  thinker   render-area width; read by ~87 functions
extern int* ScreenHeight;                     // addr: 0x009B7B20  thinker   render-area height
extern void* g_game_hwnd;                     // addr: 0x009B7B28  thinker   HWND (gui.cpp phWnd); InvalidateRect target of the soft_update family
extern struct Buffer g_screen_buffer;         // addr: 0x009B7490  observed  global screen DIB Buffer; Win_update_screen composites window buffers into it
extern struct Win* g_win_zlist[];             // addr: 0x009B6630  observed  window z-order list walked by Win_update_screen (top at [count-1])
extern int  g_win_zlist_count;                // addr: 0x009B7B30  observed  live entry count of g_win_zlist
extern void* FlatButton_vtbl;                 // addr: 0x00669754  observed  FlatButton vtable: +0x30=FlatButton_content_draw, +0xF8=GraphicWin_redraw, +0x124=GraphicWin_on_paint
extern void* BorderButton_vtbl;               // addr: 0x00670C60  guess     sibling button-class vtable; +0x30=BorderButton_content_draw; canvas subobject vtbl 0x670C58
extern void BorderButton_content_draw(void* self); // addr: 0x0062C110  observed  thiscall; fill(+0xa84) + 4 corner Sprite_draw_2 (+0xac8/+0xacc/+0xad0/+0xad4) + edge tiles; vtable-only xref (undefined in Ghidra)
extern void BorderButton_ctor(void* self);    // addr: 0x0062BF20  observed  thiscall; installs vtbl 0x670C60 + canvas vtbl 0x670C58
extern void BorderButton_ctor_2(void* self);  // addr: 0x0062C030  observed  thiscall; second ctor variant, same vtbl installs

// ============================================================================
// Window framework (Win / BaseWin / SetupWin / Console)
// ============================================================================
extern void Win_init(struct GraphicWin* self, int x, int y, int w, int h, int flags, void* parent); // addr: 0x005EBD80  thinker  thiscall; -> Buffer_init(w,h)
extern void Win_close(struct Win* self);                                         // addr: 0x005EB640  thinker   thiscall; teardown: hide, close children, unlink from parent, +0x9C = 0
extern void GraphicWin_close(struct GraphicWin* self);                           // addr: 0x005D4E40  thinker   thiscall; Win_close + free canvas Buffer +0x444
extern void Win_update_window_to_buffer(struct Win* self, void* buf);           // addr: 0x005F8140  thinker   thiscall; composites the window into buf
extern void Win_center();                      // addr: 0x005ED5C0  thinker   thiscall
extern void Win_init_class();                  // addr: 0x005F01F0  observed  also WRITES ScreenWidth/Height
extern int  WinMain();                         // addr: 0x0045F950  observed  stdcall RET 0x10; reads ini "Video Mode" + "DirectDraw"
extern int  App_init();                        // addr: 0x0062D3A0  observed  cdecl(obj,obj,title,flags,w,h,bpp); flags&4 -> Win_set_display_mode
extern int  g_app_video_flags;                 // addr: 0x009BC4B0  observed  bit 2 = DirectDraw display-mode path taken
extern const char g_str_ini_video_mode[];      // addr: 0x006853C0  observed  "Video Mode"
extern const char g_str_ini_directdraw[];      // addr: 0x006853CC  observed  "DirectDraw"
extern void* g_iat_CreateWindowExA;            // addr: 0x00669298  observed  IAT slot
extern void* g_iat_RegisterClassA;             // addr: 0x0066929C  observed  IAT slot
extern void* g_iat_ShowWindow;                 // addr: 0x00669320  observed  IAT slot
extern void* g_iat_GetSystemMetrics;           // addr: 0x00669334  observed  IAT slot; seeds ScreenWidth/Height
extern void BaseWin_init();                    // addr: 0x0041E8D0  observed  thiscall
extern struct BaseWindow BaseWin_g;            // addr: 0x006A7628  observed  the base-screen window INSTANCE; GraphicWin 758x490 FIXED at every res, pos=((SW-758)/2+16, SH-strip_h-490)
extern int* g_base_rects_ptr;                  // addr: 0x007AE7FC  observed  single write BaseWin_init@0x41E96F: = &BaseWin_g+0xA14
// field: BaseWindow +0xD7C0 FlatButton buttons[0x16]   stride 0xB4C; ctor FUN_006457c2(param_1+0x35f0 DWORDs); statics [0x6B4DE8,0x6C4670)
// field: BaseWindow +0x40C3C RECT rcMapView     tile-map viewport (seed [0xA6,0x104,0x2BB,0x15D]; copied from +0x40C4C seeds); window H = rcMapView.height + 0x191 on the !=800 branch
// field: BaseWindow +0x40C5C RECT rcCitizens    strip-side citizens-row rect (0x6E8284; MainWin-local, device space via the strip seed law); TutWin_tour6 pointer target
// field: BaseWindow +0x40C6C RECT rcProduction  strip-side production panel rect, derived in BaseWin_init from MainWin+0xD80.. strip globals (already-scaled space)
// field: BaseWindow +0x40D2C RECT rcQueueA      queue-panel rect pair (with +0x40D3C); 800-branch seeds differ
// field: BaseWindow +0x40D4C RECT rcChevBtn2    left plate-chevron button window (obj +0xEE58); built @0x41F9F5 = plate+3 + sprite dims
// field: BaseWindow +0x40D5C RECT rcChevBtn3    right plate-chevron button window (obj +0xF9A4); built @0x41FAC0 = plate.r-3 - sprite w
// field: BaseWindow +0xCAD4 Sprite* sprChevron  plate-chevron sprite obj (console-sheet extract 20x35)
// field: BaseWindow +0xCAEC int chevSpriteW     copy of sprChevron->w (+0x18); consumed by both window builds + draw_info pad
// field: BaseWindow +0xCAF0 int chevSpriteH     copy of sprChevron->h (+0x1c); consumed by the btn2 window build
// field: BaseWindow +0x40EC0 Spot spotsNative   native-space hit rects: map area (idx0 flag0, reg 0x40F1AC) + facility rows (flag2, reg 0x410337)
// field: BaseWindow +0x40ECC Spot spotsTile     per-tile hit rects, internal to the pixel->tile path
// field: BaseWindow +0x40E2C RECT rcRedBtn      staple-button art rect; frame = 9-slice 0x78d5a0 on rect+-3 @0x415B35; art windows w = r-l (exclusive right)
// field: BaseWindow +0x18C80 FlatButton winRedBtnA  staple button = FlatButton #16 (abs 0x6C02A8, array base+16*0xB4C); GraphicWin_init @0x420743 from rcRedBtn (pos l,t size r-l,b-t)
// field: BaseWindow +0xBE80 GraphicWin winRedBtnB   second button window off the same rcRedBtn (state twin); GraphicWin_init @0x4207DE
// field: BaseWindow +0x40B44 int clickStashX    raw device click x, stored @0x41B15B on lbdown
// field: BaseWindow +0x40B48 int clickStashY    raw device click y, stored @0x41B161
// field: BaseWindow +0x40130 int clickStashX2   second stored click pair (writer @0x41DEB7)
// field: BaseWindow +0x40134 int clickStashY2   second stored click pair (writer @0x41DEBF)
// field: BaseWindow +0x40B8C RECT rcRspPanel    R/S/P tab content panel (abs 0x6E81B4 in BaseWin_g; seed l=0xA6 @0x41E9D3); MapWin_init_2 mode-2 sizes the support map win from it; BaseWin_click bubble box (+0x102E3 dwords)
// field: BaseWindow +0x1E674 struct Console supportMapWin   embedded world-map Console for the SUPPORT tab (W/H = its GraphicWin +0x4C4/+0x4C8 = BaseWin +0x1EB38/+0x1EB3C)
// field: BaseWindow +0x435A0 struct ScrollBar sbSupported   FORCES SUPPORTED list scrollbar (=0x6EABC8; ScrollBar_attach_rect @0x40CC1A on [listR-3-12, top, listR-3, bot]; arrows +0xAAC/+0x15F8 = 0x6EB674/0x6EC1C0)
// field: BaseWindow +0x40B14 int supFirstPage   supported-list scroll position (ScrollBar_set_pos @0x40CC36)
// field: BaseWindow +0x40B20 int supSbEngaged   1 = supported-list scrollbar active (overflow branch @0x40CC57)
// field: BaseWindow +0x41454 struct ScrollBar sbFacilities   BASE FACILITIES list scrollbar (=0x6E8A7C; ScrollBar_attach_rect @0x41002C on [listR-12, top, listR, bot] parent BaseWin; arrows +0xAAC/+0x15F8 = 0x6E9528/0x6EA074; ScrollBar_subctor @0x41006D when the list fits)
// field: BaseWindow +0x3F308 struct ScrollBar sbFirst   first of the ctor's three ScrollBars (0x6E6930; +0x41454 facilities, +0x435A0 supported)
// field: BaseWindow +0x40B10 int facFirstRow    facilities-list scroll position (ScrollBar_set_pos @0x410048; written by BaseWin_on_scrolled @0x41B4AE)
// field: BaseWindow +0x41E94 int facPageRows    facilities rows per page - 1 (@0x410055)
// field: BaseWindow +0x40BAC RECT rcFacilities  BASE FACILITIES list panel rect (native design space; inner rect = +-3; the list bottom is rcFacBtn.top while winFacBtn is visible)
// field: BaseWindow +0x1C4FC BaseButton winFacBtn   button below the facilities list (id 0x15, BaseButton_init @0x4208A9 on rcFacBtn, label Strings_get([0x9B90F8]+0xD3C)); Win_is_visible @0x40FEB5 shortens the list to its top
// field: BaseWindow +0x40E7C RECT rcFacBtn      winFacBtn design rect (native)
// field: BaseWindow +0x40B7C RECT rcSupportedPanel   FORCES SUPPORTED strip panel (MainWin-local device space; draw_supported's clip + outer box)
// field: BaseWindow +0x40B5C RECT rcSupportedHdr     FORCES SUPPORTED header box (MainWin-local device)
// field: BaseWindow +0x40B6C RECT rcSupportedList    FORCES SUPPORTED list box (MainWin-local device; inset 3 = the unit grid)
extern void* BaseWin_vtbl;                      // addr: 0x0066A40C  observed  BaseWin vtable (stored @0x4086E5): +0x30 BaseWin_on_redraw, +0xC0 BaseWin_on_scrolled, +0xC4 0x41B4C0 (forwards to +0xC0), +0xE4 Win_set_modal, +0xFC GraphicWin_present_default; the base screen is NOT modal (g_modal_top == 0 while a base is open, Frida-measured 2026-09-22) -- "base screen up" = BaseWin_g +0x9C bit0 (Win_is_visible)
extern int  BaseWin_ctor(struct BaseWindow* self); // addr: 0x00408490  thinker  thiscall
extern int  BaseWin_map_pixel_to_tile(struct BaseWindow* self, int x, int y); // addr: 0x00409100  observed  thiscall RET 8; native-space (bounds 0x180/0xC0, tile divisors 0x60/0x30); -1 = miss; callers 0x40A2AC/0x40A2C0/0x40AE70/0x41B34D/0x41B35D/0x41B374/0x41E268/0x41E27B/0x41E295
extern void BaseWin_exit(struct BaseWindow* self); // addr: 0x0041A4C0  thinker  thiscall; Console_center when the map cursor is off screen or within 2 tiles of the edge
extern void BaseWin_base_killed(struct BaseWindow* self, int base_id); // addr: 0x0041A620  thinker  thiscall RET 4; Console_center when the cursor is near the edge
extern void BaseWin_zoom(struct BaseWindow* self, int base_id, int a3); // addr: 0x0041A920  thinker  thiscall; opens the base screen
extern void BaseWin_on_button_clicked(struct BaseWindow* self, int id); // addr: 0x0041D500  thinker  thiscall RET 4; close button: Console_center when in move mode and the selected unit is 2+ tiles off screen
extern int  tile_on_screen_margin(int x, int y, int margin); // addr: 0x004216F0  guess  thiscall RET 0xC (this=Console); nonzero = tile at least margin tiles inside the view
extern void BaseWin_show(struct BaseWindow* self); // addr: 0x0041E890  thinker  thiscall
extern void BaseWin_hide(struct BaseWindow* self); // addr: 0x0041E8B0  thinker  thiscall
extern void BaseWin_on_redraw(struct BaseWindow* self); // addr: 0x0041E790  thinker  thiscall
extern void BaseWin_on_status(struct BaseWindow* self, int is_visible); // addr: 0x0041DAD0  thinker  thiscall; base-mode enter/leave
// field: BaseWindow +0xB194 int prodPickerAction   production-picker result action; 1 = Help
extern void BaseWin_draw_nutrients(struct BaseWindow* self, int a2);   // addr: 0x00411240  thinker  thiscall; G2 panel
extern void BaseWin_draw_commerce(struct BaseWindow* self, int a2);    // addr: 0x00410870  thinker  thiscall; G3 panel
extern void BaseWin_draw_misc(struct BaseWindow* self, int a2);        // addr: 0x00415730  thinker  thiscall; G4 M.Y./Energy/Eco
extern void BaseWin_draw_farm(struct BaseWindow* self, int a2);        // addr: 0x0040F0F0  thinker  thiscall; G5 base tile map
extern void BaseWin_draw_energy_alloc(struct BaseWindow* self, int a2); // addr: 0x00411980  thinker  thiscall; G7/G8 rows
extern void BaseWin_draw_facilities(struct BaseWindow* self, int a2);  // addr: 0x0040FCC0  thinker  thiscall; G9 list
extern void BaseWin_on_scrolled(struct BaseWindow* self, int id, int value); // addr: 0x0041B4A0  observed  thiscall RET 8; id 1 = facilities bar -> facFirstRow = value, BaseWin_draw_facilities(1)
extern void BaseWin_draw_production(struct BaseWindow* self, int a2);  // addr: 0x0040E360  thinker  thiscall; G11 bottom-left preview
extern void BaseWin_draw_queue(struct BaseWindow* self, int a2);       // addr: 0x00415080  thinker  thiscall; G12 queue
extern void BaseWin_draw_pop(struct BaseWindow* self, int a2);         // addr: 0x00414B40  thinker  thiscall; G14 citizens row
extern void BaseWin_psych_row(struct BaseWindow* self, int x, int y, int w, int h, int a6, int a7, int a8); // addr: 0x00408720  thinker  thiscall; PSYCH tab face row
extern void base_research(void);                                       // addr: 0x004F4E80  thinker  cdecl; halves labs for facility 23
extern void base_drones(void);                                         // addr: 0x004F5CE0  thinker  cdecl; riot / golden age check
extern int game_rand(void);                                            // addr: 0x0064601D  thinker  cdecl; C runtime rand 0..32767
extern struct CFacility Facility[];                                    // addr: 0x009A4B68  thinker  stride 0x30, name at +0
extern struct MFaction MFactions[8];                                   // addr: 0x00946A50  thinker  stride 0x59C
// field: MFaction +0x04 char filename[24]   the faction's art file stem ("<filename>.pcx")
extern void* g_iat_timeGetTime;                                        // addr: 0x00669368  observed  IAT slot
extern void drone_riot(void);                                          // addr: 0x004F4FB0  thinker  cdecl; CurrentBase riot + defection
extern void base_psych(void);                                          // addr: 0x004EA540  thinker  cdecl; CurrentBase psych stages
extern int has_fac_built(int fac_id);                                  // addr: 0x00500290  thinker  cdecl; uses CurrentBaseID
extern void base_energy(void);                                         // addr: 0x004EB560  thinker  cdecl; tail calls base_psych @0x4EC39A
extern int  base_compute(int update_prev);                             // addr: 0x004EC3B0  thinker  cdecl; skips when ComputeBaseID == CurrentBaseID and arg 0; last step base_energy
extern void set_base(int base_id);                                     // addr: 0x004E39D0  thinker  cdecl
extern struct BASE* CurrentBase;                                       // addr: 0x0090EA30  thinker
extern int CurrentBaseID;                                              // addr: 0x00689370  thinker
extern int ComputeBaseID;                                              // addr: 0x00689374  thinker  base whose computed values are current
extern int BaseUpkeepState;                                            // addr: 0x0090EA34  thinker  1 = upkeep (base_psych scores social_psych)
extern int BasePsychNDrones[5];                                        // addr: 0x0090E920  thinker  drones per psych stage
extern int BasePsychSDrones[5];                                        // addr: 0x0090E94C  thinker  superdrones per psych stage
extern int BasePsychTalents[5];                                        // addr: 0x0090E984  thinker  talents per psych stage
extern struct Sprite g_citizen_sprites_human_lg[];                     // addr: 0x0078CAD0  observed  38x48, stride 0x2C, idx + 4*variant
extern struct Sprite g_citizen_sprites_alien_lg[];                     // addr: 0x007AD1B0  observed  38x48, stride 0x2C
extern struct Sprite g_citizen_sprites_human_sm[];                     // addr: 0x00776420  observed  30x38, stride 0x2C
extern struct Sprite g_citizen_sprites_alien_sm[];                     // addr: 0x0075B180  observed  30x38, stride 0x2C
extern void BaseWin_draw_garrison(struct BaseWindow* self, int a2);    // addr: 0x004103B0  thinker  thiscall; G15 garrison row
extern void BaseWin_draw_supported(struct BaseWindow* self, int a2);   // addr: 0x0040C850  thinker  thiscall; G16 FORCES SUPPORTED
extern void BaseWin_draw_flash(struct BaseWindow* self, int a2);       // addr: 0x0040D250  thinker  thiscall
extern void BaseWin_draw_expenses(struct BaseWindow* self, int a2);    // addr: 0x00412AA0  thinker  thiscall
extern void BaseWin_draw_info(struct BaseWindow* self, int a2);        // addr: 0x00415B20  thinker  thiscall
extern void BaseWin_draw_psych(struct BaseWindow* self);               // addr: 0x00408B20  thinker  thiscall
extern void BaseWin_draw_support(struct BaseWindow* self);             // addr: 0x00408EB0  thinker  thiscall
// Production picker (base build-choice grid dialog; object = BaseWin_g+0xA1C = 0x6A8044; NOT the BasePop pipeline)
extern void BaseWin_production(struct BaseWindow* self, int a2, int a3); // addr: 0x00417040  thinker  thiscall; production/queue driver: save-under win 0x4176E1, ProdPicker_exec 0x417771, RETOOLPENALTY popup 0x417B97
extern int  ProdPicker_exec(struct ProdPicker* self, void* base_ptr, int faction_id, struct GraphicWin* saveunder, int queue_mode); // addr: 0x00494700  observed  thiscall RET 0x10; builds window+buttons+scrollbar, modal loop vtbl+0xE4 @0x494FB7/0x494FE8, returns item value (facility -id / unit +id / -9999); sole caller 0x417771
extern struct ProdPicker* ProdPicker_ctor(struct ProdPicker* self);    // addr: 0x00492420  observed  fastcall; from BaseWin_ctor @0x4084CB; seeds +0xA830/+0xA834=0x86 @0x492667, +0xA838=0x6C @0x492689, +0xA83C=0x5E @0x492693; vtbl store @0x492679
extern void ProdPicker_build_items(struct ProdPicker* self);           // addr: 0x00492FA0  observed  fastcall; fills 3 item lists; grid layout tail 0x49393D-0x493A6C: w/h=BaseWin+0x4C4/-0x4C8 @0x49394B/0x493959, cols init 5 @0x493967, vis_rows=3+(ScreenWidth>800) @0x493971-0x49398A, colw=(w-0x51)/5 @0x493977, pitch=[+0xA838] @0x4939A4; Font_init x4 @0x4939DB/0x493A13/0x493A4B/0x493A61
extern void ProdPicker_draw_cell(struct ProdPicker* self, int item, int flush); // addr: 0x004927C0  observed  thiscall RET 8; cell rect {col*colw+0x1B, row*pitch+4, (col+1)*colw+0x18, row*pitch+pitch+1} @0x4927EF-0x492853; frame d528+0x50-if-sel @0x49287E; name font +0xA9C 3-line band y+6 @0x492A8E-0x492AF7; turns text @0x492BFB; stats bottom-anchored @0x492B9B; unit zoom=pitch*2/3 @0x492C0B, veh_draw @0x492CDB, Caviar flag @0x492D6F; fac icon=pitch*3/7 @0x492E65, draw @0x492F52; sel outline Buffer_box_2 @0x492F74
extern void ProdPicker_draw_visible(struct ProdPicker* self);          // addr: 0x00493C70  observed  fastcall; redraws items [+0xA77C]..+[+0xA82C]
extern void ProdPicker_scroll_to(struct ProdPicker* self, int a2, int row); // addr: 0x00493CB0  observed  thiscall RET 8; |delta|<=cols: Buffer_copy_4 self-blit @0x493D69/0x493E23 + draw exposed row, else vtbl+0xF8
extern void ProdPicker_on_scroll_drag(/*ecx*/ struct ProdPicker* self, int id, int value); // addr: 0x00493E70  observed  thiscall RET 8; vtbl+0xC4 (drag/repeat notify)
extern void ProdPicker_select_from_xy(struct ProdPicker* self, int x, int y); // addr: 0x004941C0  observed  thiscall RET 8; vtbl+0x4C; LOCAL coords, sel=[+0xA77C]+(y/pitch)*count+x/colw (no inset sub); redraws old+new selected cell
extern void ProdPicker_page_nav(struct ProdPicker* self, int delta);   // addr: 0x00494280  observed  thiscall; scroll paging + ScrollBar_set_pos
extern void ProdPicker_on_button_clicked(struct ProdPicker* self, int id); // addr: 0x004945D0  observed  thiscall; btn ids: -2 HELP, -1 CANCEL, 0 OK, 1 (4-btn variant), 6 WORKSHOP, 4/5/7 queue REPLACE/INSERT/DELETE -> result [+0xA778]
extern void ProdPicker_anim_tick(int a1, struct ProdPicker* self);     // addr: 0x004946D0  observed  cdecl; pop_expire cb: [+0xB64]++ then redraw selected cell (flag wave)
extern void ProdPicker_right_menu(struct ProdPicker* self, int a2, int a3); // addr: 0x00493EA0  observed  thiscall; right-click context Menu
extern void* ProdPicker_vtbl;                  // addr: 0x0066A250  observed  picker vtable; +0x30=draw_visible +0x3C=scroll-delta +0x4C=select_from_xy +0x58=right_menu +0xB0=on_button_clicked +0xC0=scroll_to +0xE4=modal exec
// field: ProdPicker +0x444 struct Buffer canvas      standard GraphicWin canvas (clip +0x474, w +0x4C4, h +0x4C8 NEG)
// field: ProdPicker +0xA9C struct Font fontCellName  Font_init(g_hud_font_name,12,1) FIXED @0x4939DB; cell name text
// field: ProdPicker +0xAC4 struct Font fontBig       Font_init(hud,max(24,colw/15),1) @0x493A13; no in-picker reader found
// field: ProdPicker +0xAEC struct Font fontCellStats Font_init(hud,max(10,colw/15),0) @0x493A4B; turns/cost + stats lines; [+0]=3 line-pad forced @0x492B09
// field: ProdPicker +0xB14 struct Font fontButton    Font_init(hud,14,1) FIXED @0x493A61; set on all 8 buttons @0x494F17
// field: ProdPicker +0x7120 struct ScrollBar sb      ScrollBar_init_inner @0x4949DE at (w-0x14, 0x15, 0x18, 0x13A) NATIVE consts; engaged iff vis_cells < item_count @0x4949B1
// field: ProdPicker +0xA76C int faction_id
// field: ProdPicker +0xA770 void* base_ptr
// field: ProdPicker +0xA774 int sel_item             -1 = none
// field: ProdPicker +0xA778 int result_code          from on_button_clicked
// field: ProdPicker +0xA77C int first_vis_item
// field: ProdPicker +0xA788 void* listNames          item name list (head +0xA788, cursor +0xA78C, count +0xA790); node: +4 value, +8 str-obj, +0xC next, +0x10 prev
// field: ProdPicker +0xA7B8 void* listTurns          turns/cost text list (same triplet shape)
// field: ProdPicker +0xA7E8 void* listStats          stats text list (same triplet shape)
// field: ProdPicker +0xA810 int cols                 recomputed (w-0x51)/colw @0x4939C2 (=5)
// field: ProdPicker +0xA814 int vis_rows             3+(ScreenWidth>800) @0x49398A
// field: ProdPicker +0xA818 int item_count
// field: ProdPicker +0xA81C int col_w                (w-0x51)/5 @0x4939B9
// field: ProdPicker +0xA820 int row_pitch            copy of +0xA838 @0x4939AA; drives cell rects, icon sizes, button-row Y
// field: ProdPicker +0xA824 int win_w                = BaseWin+0x4C4 @0x493953
// field: ProdPicker +0xA828 int win_h                = -(BaseWin+0x4C8) @0x493961
// field: ProdPicker +0xA82C int vis_cells            vis_rows*cols @0x4939C8
// field: ProdPicker +0xA838 int row_pitch_seed       =0x6C(108) ctor @0x492689; THE native row-height lever (+0xA830/+0xA834=0x86 and +0xA83C=0x5E have no readers)
// field: ProdPicker +0xB64 int anim_counter
// field: ProdPicker +0xB68 int queue_mode
// field: ProdPicker +0xB6C int btn_count             6 queue @0x494A83 / 4 @0x494A99 / 5 with WORKSHOP @0x494ACA
// field: ProdPicker +0xB70 int btn_w                 =0x64(100) @0x4949B3 NATIVE; btn h = 0x14 push @0x494B6E
// field: ProdPicker +0xB74 struct FlatButton buttons[9]   stride 0xB4C; ctor array @FUN_006457C2 in ProdPicker_ctor; BaseButton_init sites 0x494B80/0x494BF4/0x494C59/0x494CBF/0x494D25/0x494DBD/0x494E23/0x494E89/0x494EF4
// field: BaseWindow +0xA1C struct ProdPicker prodPicker   abs 0x6A8044; sizeof >= 0xB74+9*0xB4C
// Holobook = end-game rating book (quayle 0x496670, NOT the Datalinks screen); the in-game DATALINKS window is DatalinkWin_g below
extern struct Holobook* Holobook_g;            // addr: 0x00872CB0  observed  function-local static; lazy ctor stub 0x495170
extern struct Holobook* Holobook_ctor(struct Holobook* self); // addr: 0x00496810  observed  installs vtbl 0x66D598 @ctor end 0x4968B3
extern void* Holobook_vtbl;                    // addr: 0x0066D598  observed  +0x30=draw 0x4956D0 +0xE4=modal exec
extern void Holobook_draw(struct Holobook* self); // addr: 0x004956D0  observed  vtbl+0x30; BOOKTITLE/BOOKINTRO/art; canvas self+0x444; native rect seeds from gwinit; fonts [0x8A40E4]/[0x8A40E8]/[0x8A40F0]
extern void Holobook_gwinit(struct Holobook* self); // addr: 0x004951A0  observed  800x600 if [0x8A4168]==0 else 1024x768 @(0x77,0x50); rect seeds 0x4952E9-0x4953C6 all native immediates
extern int  Holobook_open_item(int item_id);   // addr: 0x00496610  observed  open on facility/project entry
extern int  Holobook_open_unit(int unit_id);   // addr: 0x00496670  observed  triangular chapter index; callers 0x514CE9/0x5256A4
// ==== DATALINKS encyclopedia window (DatalinkWin, mode-8 SubInterface; static map work\_dl_static_map.md) ====
extern struct DatalinkWindow DatalinkWin_g;                                    // addr: 0x00703EA0  thinker  global object; size 0x1B394; vtbl 0x66AF84, buffer vtbl 0x66AF7C @+0x444, iface vtbl 0x66AF30 @+0xA14
extern void  DatalinkWin_ctor(/*ecx*/ struct DatalinkWindow* self);           // addr: 0x00428FC0  observed  fastcall; static-init thunk 0x428F90, atexit dtor thunk 0x428FB0; FlatButton[0x12] @+0x2A3C, ListBox @+0xF628, Font x11 @+0x1017C, TextScroll x4 @+0x10514
extern void  DatalinkWin_dtor(/*ecx*/ struct DatalinkWindow* self);           // addr: 0x00432290  observed  fastcall; vtbl+0 thunk 0x432800
extern void  DatalinkWin_build(/*ecx*/ struct DatalinkWindow* self);          // addr: 0x00429300  observed  fastcall; ALL rect seeds + 11 Font_init + GraphicWin_init @0x429A23 + 18 BaseButton_init + 3 TextScroll_attach; callers system_init 0x58F22A, 0x590DCF
extern void  DatalinkWin_open(/*ecx*/ struct DatalinkWindow* self, int category, int item); // addr: 0x00429180  observed  thiscall RET 8; modal entry (Win_set_modal); 26 callers (help_*, diplo DATALINKS, StatusWin rclick cat 9, TechWin rclick cat 0xE)
extern void  DatalinkWin_set_category(/*ecx*/ struct DatalinkWindow* self, int category, int force); // addr: 0x0042A2C0  observed  thiscall RET 8; populates ListBox via 16 builders 0x42A4F0..0x42BAB0 + inline category-title paint; ButtonGroup_set_by_id
extern void  DatalinkWin_render_topic(/*ecx*/ struct DatalinkWindow* self);   // addr: 0x0042BF10  observed  fastcall; text-panel repaint: backdrop d690 @0x42C020, d528 @0x42C03E, d618 @0x42C051, hides 4 TextScrolls, per-category painter switch
extern void  DatalinkWin_repaint(/*ecx*/ struct DatalinkWindow* self);        // addr: 0x00431E70  observed  fastcall; vtbl+0x30: clip 0x7AEC94 + MainWin_tile_panels(1) + render_topic
extern void  DatalinkWin_show(/*ecx*/ struct DatalinkWindow* self);           // addr: 0x0042BD40  observed  vtbl+0x4; SubInterface_set_iface_mode if hidden
extern void  DatalinkWin_hide(/*ecx*/ struct DatalinkWindow* self);           // addr: 0x0042BD60  observed  vtbl+0x8; SubInterface_release_iface_mode if visible
extern void  DatalinkWin_on_button_clicked(/*ecx*/ struct DatalinkWindow* self, int id); // addr: 0x00431EC0  observed  vtbl+0xB0 RET 4; 0x10 BACK (history pop) / 0x11 EXIT (release modal) / cat 0xE -> ReportWin_tech_button 0x4986D0
extern int   DatalinkWin_on_key(/*ecx*/ struct DatalinkWindow* self, int key, int vk); // addr: 0x00431FC0  observed  vtbl+0x64 RET 8; Enter/Esc release modal, else forward to ListBox vtbl+0x68
extern int   DatalinkWin_on_link_click(/*ecx*/ struct DatalinkWindow* self, int a2, const char* link); // addr: 0x00431DC0  observed  vtbl+0x160 RET 8; atoi(link) = cat*10000+item; item>1000 rejected
extern void  DatalinkWin_on_list_select(/*ecx*/ struct DatalinkWindow* self, int a2); // addr: 0x00432040  observed  vtbl+0xD8 RET 4; render_topic unless history-suppress +0x2A38
extern void  DatalinkWin_on_mouse_move(/*ecx*/ struct DatalinkWindow* self, int x, int y); // addr: 0x00432010  observed  vtbl+0xA0 RET 8; cat 0xE -> ReportWin_tech_hover(0x876478,id,state)
extern int   DatalinkWin_list_bg_fill(/*ecx*/ struct DatalinkWindow* self);    // addr: 0x0042A100  observed  vtbl+0x28 (= FileDlg_bg_fill shared slot); Buffer_tile navy dither over ListBox rect; baked redirect @0x42A140
extern int   DatalinkWin_list_row_bg(/*ecx*/ struct DatalinkWindow* self, void* win, int id, int state, RECT* r); // addr: 0x0042A150  observed  vtbl+0x2C RET 0x10; Buffer_tile g_filedlg_rowtile_unsel / 0x78D980 hover / 0x78D9A8 selected; cat 0xC text colour 0xFF-item/5
extern void  DatalinkWin_go_back(/*ecx*/ struct DatalinkWindow* self);         // addr: 0x0042BE00  observed  fastcall; history pop + set_category + render_topic
extern void  DatalinkWin_select_item(/*ecx*/ struct DatalinkWindow* self, int item); // addr: 0x0042BCC0  observed  thiscall RET 4; ListBox_set_selected_id(cat*10000+item) + list redraw
extern void  DatalinkWin_goto(/*ecx*/ struct DatalinkWindow* self, int category, int item); // addr: 0x0042A260  observed  thiscall RET 8; set_category(cat,0) + select_item
extern void  DatalinkWin_push_history(/*ecx*/ struct DatalinkWindow* self, int category, int item); // addr: 0x0042BD80  observed  thiscall RET 8; ring of 20 at +0x29E4
extern void  DatalinkWin_show_console_text(/*ecx*/ struct DatalinkWindow* self, const char* file, const char* key); // addr: 0x0042BEB0  observed  thiscall RET 8; loads text into console TextScroll +0x130B4 when g_console_big_center
extern void  DatalinkIface_on_mode(struct SubInterface* self, int enter);      // addr: 0x00432060  observed  thiscall RET 4; iface vtbl 0x66AF30+0; enter: repaint + slide_show(win,2) + render_topic + Win_show + 18 buttons + ListBox show; exit: slide_hide(win,2)
extern void  DatalinkIface_on_button(struct SubInterface* self, int a2, int a3, int id); // addr: 0x00432210  observed  iface vtbl+0x40 RET 0xC; wing button: set_category(id,0) + ListBox_set_selected_pos(0,1) + render_topic
extern void  DatalinkWin_list_all(/*ecx*/ struct DatalinkWindow* self);        // addr: 0x0042A4F0  observed  fastcall; cat 2 ALL CATEGORIES builder (calls the other 14)
extern void  DatalinkWin_list_concepts(/*ecx*/ struct DatalinkWindow* self);   // addr: 0x0042B300  observed  fastcall; cat 0 builder (CONCEPTSX #TITLES); title d618 @+0x103D4 font +0x101CC colour 0xE0
extern void  DatalinkWin_list_adv_concepts(/*ecx*/ struct DatalinkWindow* self); // addr: 0x0042B490  observed  fastcall; cat 1 builder
extern void  DatalinkWin_list_units(/*ecx*/ struct DatalinkWindow* self);      // addr: 0x0042A630  observed  fastcall; cat 3 builder (Units table 0x9AB868 stride 0x34, ids 30000+i)
extern void  DatalinkWin_list_chassis(/*ecx*/ struct DatalinkWindow* self);    // addr: 0x0042A790  observed  fastcall; cat 4 builder
extern void  DatalinkWin_list_reactors(/*ecx*/ struct DatalinkWindow* self);   // addr: 0x0042A900  observed  fastcall; cat 5 builder
extern void  DatalinkWin_list_weapons(/*ecx*/ struct DatalinkWindow* self);    // addr: 0x0042AA60  observed  fastcall; cat 6 builder
extern void  DatalinkWin_list_armor(/*ecx*/ struct DatalinkWindow* self);      // addr: 0x0042ABC0  observed  fastcall; cat 7 builder
extern void  DatalinkWin_list_abilities(/*ecx*/ struct DatalinkWindow* self);  // addr: 0x0042AD20  observed  fastcall; cat 8 builder
extern void  DatalinkWin_list_terraform(/*ecx*/ struct DatalinkWindow* self);  // addr: 0x0042BAB0  observed  fastcall; cat 9 builder
extern void  DatalinkWin_list_facilities(/*ecx*/ struct DatalinkWindow* self); // addr: 0x0042AE80  observed  fastcall; cat 10 builder
extern void  DatalinkWin_list_projects(/*ecx*/ struct DatalinkWindow* self);   // addr: 0x0042AFE0  observed  fastcall; cat 11 builder (item = facility id 0x46+)
extern void  DatalinkWin_list_social_models(/*ecx*/ struct DatalinkWindow* self); // addr: 0x0042B630  observed  fastcall; cat 12 builder
extern void  DatalinkWin_list_social_effects(/*ecx*/ struct DatalinkWindow* self); // addr: 0x0042B7E0  observed  fastcall; cat 13 builder
extern void  DatalinkWin_list_techs(/*ecx*/ struct DatalinkWindow* self);      // addr: 0x0042B190  observed  fastcall; cat 14 builder
extern void  DatalinkWin_list_factions(/*ecx*/ struct DatalinkWindow* self);   // addr: 0x0042B940  observed  fastcall; cat 15 builder
extern void  DatalinkWin_draw_concept(/*ecx*/ struct DatalinkWindow* self);    // addr: 0x0042C2E0  observed  fastcall; cat 0 page: title F0 @+0x10364, text -> TextScroll +0x10514 (full panel)
extern void  DatalinkWin_draw_adv_concept(/*ecx*/ struct DatalinkWindow* self); // addr: 0x0042C650  observed  fastcall; cat 1 page (same shape as cat 0)
extern void  DatalinkWin_draw_unit(/*ecx*/ struct DatalinkWindow* self);       // addr: 0x0042C9C0  observed  fastcall; cat 3 page: veh_draw at (+0x10354.L,.T) size 4 flags 0x40, stats write_strings, HELPX -> TextScroll +0x15C54
extern void  DatalinkWin_draw_chassis(/*ecx*/ struct DatalinkWindow* self);    // addr: 0x0042D610  observed  fastcall; cat 4 page: Caviar zoom 0.1 centred in +0x10354
extern void  DatalinkWin_draw_reactor(/*ecx*/ struct DatalinkWindow* self);    // addr: 0x0042DEF0  observed  fastcall; cat 5 page: Caviar zoom 0.2
extern void  DatalinkWin_draw_weapon(/*ecx*/ struct DatalinkWindow* self);     // addr: 0x0042E2E0  observed  fastcall; cat 6 page: Caviar zoom by class; text x inset +6
extern void  DatalinkWin_draw_armor(/*ecx*/ struct DatalinkWindow* self);      // addr: 0x0042E8E0  observed  fastcall; cat 7 page: Caviar zoom 0.15/0.2 (+Caviar_overlay)
extern void  DatalinkWin_draw_ability(/*ecx*/ struct DatalinkWindow* self);    // addr: 0x0042EE30  observed  fastcall; cat 8 page: text only (HELPABIL)
extern void  DatalinkWin_draw_terraform(/*ecx*/ struct DatalinkWindow* self);  // addr: 0x00431180  observed  fastcall; cat 9 page: 55px terrain tile composite (Sprite_draw_2 x13, Texture_draw 0x61B1F0 x2, 0x61C090 x6) in +0x10384
extern void  DatalinkWin_draw_facility(/*ecx*/ struct DatalinkWindow* self);   // addr: 0x0042F490  observed  fastcall; cat 10 page: Sprite_draw_2 @0x42F5CF (sprite 0x787200+id*0x2C, num=boxW 127, den=sprite w) into +0x10354; text -> console TextScroll +0x130B4
extern void  DatalinkWin_draw_project(/*ecx*/ struct DatalinkWindow* self);    // addr: 0x0042FAD0  observed  fastcall; cat 11 page: Sprite_draw_2 @0x42FC0C (sprite 0x759320+(id-0x46)*0x2C, den=[0x759338])
extern void  DatalinkWin_draw_social_model(/*ecx*/ struct DatalinkWindow* self); // addr: 0x00430090  observed  fastcall; cat 12 page: text + effect table (write_l_4/write_right_l_5) in +0x10394 inset 3
extern void  DatalinkWin_draw_social_effect(/*ecx*/ struct DatalinkWindow* self); // addr: 0x00430770  observed  fastcall; cat 13 page: text only
extern void  DatalinkWin_draw_faction(/*ecx*/ struct DatalinkWindow* self);    // addr: 0x00430C80  observed  fastcall; cat 15 page: portrait Sprite_draw_2 1:1 @0x430DA3 at (+0x10334.L+5,.T+5); profile -> console TextScroll
extern void  DatalinkWin_draw_tech_title(/*ecx*/ struct DatalinkWindow* self); // addr: 0x00430B30  observed  fastcall; cat 14 helper: title + ReportWin_tech_page + BLURBSX console text
extern void  TextScroll_draw(/*ecx*/ void* self);                              // addr: 0x00629B70  observed  vtbl 0x66ADC8+0x30; GraphicWin_clear(9), text at (0,0) width +0x4C4 (minus +0x1480 when +0xABC&1), Buffer_write_strings / per-line wrap from +0xA1C
extern void  TextScroll_set_first_line(/*ecx*/ void* self, int id, int line);  // addr: 0x00629D20  observed  vtbl+0xC0 RET 8; +0xA1C = line, redraw
extern void  TextScroll_clear(/*ecx*/ void* self);                             // addr: 0x00629780  observed  fastcall; frees internal list, hides ScrollBar +0xA20
extern void  TextScroll_finish(/*ecx*/ void* self);                            // addr: 0x00629490  observed  fastcall; trims to +0xA18 max lines, shows/hides ScrollBar, ScrollBar_set_pos
extern void  TextScroll_dtor(/*ecx*/ void* self);                              // addr: 0x004325C0  observed  fastcall; vtbl+0 thunk 0x432770
extern int   TextScroll_on_link_click(/*ecx*/ void* self, int a2, const char* link); // addr: 0x00432720  observed  vtbl+0x160 RET 8; forwards to parent [+0xC4] vtbl+0x160 when parent vtbl+0xF4 != 0
extern int   TextList_load(/*ecx*/ void* list, const char* file, const char* key, int a4, int a5); // addr: 0x00608980  observed  thiscall; loads a text section (HELPX/BLURBSX/...) into a string list
extern struct ReportWindow ReportWin_g;                                        // addr: 0x00876478  thinker  ReportWin; its tech page painter is reused inside DatalinkWin (mode 8)
extern void  ReportWin_tech_page(/*ecx*/ struct ReportWindow* self);           // addr: 0x00498B30  observed  fastcall; tech info card + 6 FlatButtons ids 0x379..0x37E; in Datalinks mode reads rec
extern void  ReportWin_tech_connector(/*ecx*/ struct ReportWindow* self, int x1, int y1, int x2, int y2, int btnW, int btnH, int hover); // addr: 0x0049B450  observed  thiscall RET 0x1C; bracket/chevron painter (pair boxes drawn under per-row clips)
extern void  Sprite_draw_mono_scaled(/*ecx*/ struct Sprite* spr, void* dest, int key, int x, int y, int col, int num, int den); // addr: 0x005E3E00  observed  thiscall RET 0x1C; SCALE_NUM_G/DEN swap + Sprite_draw_mono_2t DatalinkWin+0x103A4 (0x714244), buttons parent DatalinkWin
extern void  ReportWin_tech_reset(/*ecx*/ struct ReportWindow* self);          // addr: 0x00496BB0  observed  fastcall; hides 7 tech FlatButtons (+0xA38 stride 0xB4C), reset fonts/rects
extern void  ReportWin_tech_button(/*ecx*/ struct ReportWindow* self, int id); // addr: 0x004986D0  observed  thiscall RET 4; prereq/leads-to buttons -> DatalinkWin_open re-entrant (9 sites)
extern void  ReportWin_tech_hover(/*ecx*/ struct ReportWindow* self, int btn_id, int highlight); // addr: 0x0049B220  observed  thiscall RET 8; ReportWin vtbl+0xA0; ids >=0x378, kind 2 only; frames d5f0 (on) / d5a0 (off) + connector
extern void* ReportWin_vtbl_tech_hover_slot;                                       // addr: 0x0066D7F4  observed  ReportWin vtbl 0x66D754 + 0xA0 = ReportWin_tech_hover
extern int   g_iface_mode_table[];                                             // addr: 0x007AE778  observed  int[]; g_iface_mode_table[g_iface_mode_idx] == 8 means DatalinkWin is the live SubInterface
extern int   g_iface_mode_idx;                                                 // addr: 0x007D392C  observed  index into g_iface_mode_table
extern struct SubInterface* g_iface_slot_8;                                    // addr: 0x007AE810  observed  = DatalinkWin+0xA14, written by DatalinkWin_build (slot = 0x7AE7F4 + (mode-1)*4)
extern int   g_reportwin_item;                                                 // addr: 0x00885F30  observed  ReportWin current item (tech id on the tech page); saved/restored by DatalinkWin_open
extern int   g_reportwin_kind;                                                 // addr: 0x00885F40  observed  ReportWin page kind (2 = tech); saved/restored by DatalinkWin_open
extern int   g_reportwin_faction;                                              // addr: 0x008A4160  observed  ReportWin faction; DatalinkWin_open sets = CurrentPlayerFaction
extern struct ScrollBar* ReportWin_energy_list_vbar;   // addr: 0x0087C308  observed  scroll_vert of the energy ListBox Win; 0 when closed
extern int   CurrentPlayerFaction;                                             // addr: 0x00939284  thinker   MapWin->cOwner; ReportIf_activate @0x4A4228 and DatalinkWin_open copy it into g_reportwin_faction
extern struct Label TextLabels;                                               // addr: 0x009B90F8  thinker   {char** labels; uint32 count}: labels.txt, one char* per label into TextTable's pool, index = file line - 11 (557 'Move unit to here', 565 'Move cursor to here|Shift+Right')
extern struct Strings TextTable;                                              // addr: 0x009B90D8  thinker   the labels' string pool
// field: Strings +0x00 uint32 flags (bit 0 = fixed, no realloc) ; +0x04 char* base ; +0x08 char* cursor ; +0x0C uint32 size ; +0x10 uint32 free
extern char* Strings_put(struct Strings* self, const char* s);                // addr: 0x00616970  thinker   thiscall RET 4; Strings_alloc(strlen+1) + strcpy, returns the pooled copy
extern char* Strings_get(struct Strings* self, char* p);                      // addr: 0x006169A0  thinker   thiscall RET 4; validates p against [base, base+size): p, or 0 when outside (p <= base returned as is)
extern char* Strings_alloc(struct Strings* self, int n);                      // addr: 0x005D4680  observed  thiscall RET 4; bumps cursor; when free < n and !(flags&1) reallocs the pool by 0x400 (the base MOVES)
extern char  g_str_scratch[];                                                  // addr: 0x009B86A0  observed  shared label compose buffer
extern struct Sprite g_facility_sprites[];                                     // addr: 0x00787200  observed  Sprite[] stride 0x2C indexed by facility id (Datalinks facility art)
extern struct Sprite g_project_sprites[];                                      // addr: 0x00759320  observed  Sprite[] stride 0x2C indexed by project id-0x46
// field: DatalinkWin +0x13C   RECT screen_rect
// field: DatalinkWin +0x444   struct Buffer canvas        vtbl 0x66AF7C; w +0x4C4 (=0x340), h +0x4C8 (NEGATIVE)
// field: DatalinkWin +0x474   RECT local_rect
// field: DatalinkWin +0xA14   struct SubInterface iface   vtbl 0x66AF30; +0xA18 mode id 8
// field: DatalinkWin +0xA1C   int  saved_reportwin_item   ; +0xA20 saved kind ; +0xA24 saved faction
// field: DatalinkWin +0xA28   struct Flic flic            Flic_ctor 0x629D60 (+ Palette); 0xAE4 B
// field: DatalinkWin +0x150C  struct Caviar caviar        0x14D0 B; part renders for chassis/reactor/weapon/armor pages
// field: DatalinkWin +0x29DC  int  category               0..15 (ctor default 2)
// field: DatalinkWin +0x29E0  int  item
// field: DatalinkWin +0x29E4  int  history[20]            cat*10000+item ring
// field: DatalinkWin +0x2A34  int  history_count
// field: DatalinkWin +0x2A38  int  history_suppress
// field: DatalinkWin +0x2A3C  struct FlatButton buttons[0x12]   stride 0xB4C, index == id; 0..15 wing (parent MainWin_g), 0x10 BACK @+0xDEFC, 0x11 EXIT @+0xEA48 (parent self)
// field: DatalinkWin +0xF594  struct ButtonGroup wing_group  ctor 0x62B7C0; ButtonGroup_init @0x429C11
// field: DatalinkWin +0xF628  struct ListBox topic_list    ListBox_ctor(1); GraphicWin part @+0xF670 (vb +0x48), Dialog part @+0x10088 (vb +0xA60): x +0x100AC y +0x100B0 w +0x100B4 h +0x100B8, row_gap +0x100CC, row_stride +0x100D0, visible +0x100E0, line_h +0x100F0, font +0x100F8
// field: DatalinkWin +0x1017C struct Font font[11]         stride 0x28: [0] 18 bold title, [1] +0x101A4 14 list, [2] +0x101CC 14 bold category title, [3] +0x101F4 14 bold buttons, [4] +0x1021C 14 bold, [5] +0x10244 14 bold body, [6] +0x1026C 14, [7] +0x10294 12 console text, [8] +0x102BC 14 style5 hyperlink, [9] +0x102E4 14 style4, [10] +0x1030C 14  (800x600: 12/12/18/14x4/14/14/10/14st5 per build)
// field: DatalinkWin +0x10334 RECT text_panel            union(upper,lower) {0xEF,0x24,0x302,0x143+ofs}
// field: DatalinkWin +0x10354 RECT picture_box           {0xF8,0x2C,0x177,0xAB} 127x127
// field: DatalinkWin +0x10364 RECT topic_title           {0xEF,7,0x302,0x22}
// field: DatalinkWin +0x10374 RECT console_text_box      = [0x7AF5E0..EC] (MainWin rcConsoleCenterBig); TextScroll +0x130B4 inset 3, parent MainWin
// field: DatalinkWin +0x10384 RECT text_upper            {0xEF,0x24,0x302,0xB4+ofs/2}
// field: DatalinkWin +0x10394 RECT text_lower            {0xEF,0xB6+ofs/2,0x302,0x143+ofs}
// field: DatalinkWin +0x103A4 RECT text_panel_clip       copy of +0x10334 (abs 0x714244; read by ReportWin_tech_page)
// field: DatalinkWin +0x103B4 RECT right_container       union(title,upper,lower) +-3
// field: DatalinkWin +0x103C4 RECT window_rect           screen {x=(SW-800)/2, y=SH-strip-h, x+0x340, y+h}; h = (SW==800 ? 600 : 0x2E2) - strip
// field: DatalinkWin +0x103D4 RECT category_title        {0x1E,7,0xE6,0x1B}
// field: DatalinkWin +0x103E4 RECT list_box              {0x1E,0x1D,0xE6,0x143+ofs}; ListBox = inset 3
// field: DatalinkWin +0x103F8 RECT wing_rect[16]         stride 0x10, index == id; left ids 0..7 top->bottom, right ids 8..15 bottom->top; h 0x16 pitch 0x18
// field: DatalinkWin +0x104F4 RECT back_rect             {0x98,0x14E+ofs,0x18E,0x162+ofs}
// field: DatalinkWin +0x10504 RECT exit_rect             {0x192,0x14E+ofs,0x288,0x162+ofs}
// field: DatalinkWin +0x10514 struct TextScroll text_full    parent self, rect +0x10334 inset 3, fonts [5]/[8]
// field: DatalinkWin +0x130B4 struct TextScroll text_console parent MainWin_g, rect +0x10374 inset 3, font [7]
// field: DatalinkWin +0x15C54 struct TextScroll text_lower   parent self, rect +0x10394 inset 6, fonts [5]/[8]
// field: DatalinkWin +0x187F4 struct TextScroll text_lower800 attached only at 800x600 by DatalinkWin_open (rect +0x10394 +g_scrollbar_w+8), fonts [6]/[8]
// field: TextScroll +0xA14 int   mode_flag        0 = whole list via Buffer_write_strings, else per-line wrap
// field: TextScroll +0xA18 int   max_lines        -1 = unlimited
// field: TextScroll +0xA1C int   first_line
// field: TextScroll +0xA20 struct ScrollBar sb    0x214C B; ScrollBar_attach(x = w - g_scrollbar_w, y 0, h = -canvas_h, parent self, 0)
// field: TextScroll +0xABC int   flags            bit0: reserve +0x1480 px on the right for the bar
// field: TextScroll +0x1480 int  sb_reserve
// field: TextScroll +0x2B6C void* ext_list        external string list (else internal +0x2B70)
// field: TextScroll +0x2BA0 int  sizeof
// field: ReportWin +0xA38  struct FlatButton tech_btn[7]   stride 0xB4C; ids 0x379 preq1, 0x37A preq2, 0x37B..0x37E leads-to
// field: ReportWin +0x594C int  tech_col_x[4]      card/button column x (computed by ReportWin_tech_page)
// field: ReportWin +0x5958 int  tech_row_mid       y of the middle leads-to row (odd layout centre)
// field: ReportWin +0x595C int  tech_row_above     tech_row_mid - btn_h - 16 (odd layout)
// field: ReportWin +0x5960 int  tech_row_below     tech_row_mid + btn_h + 16 (odd layout)
// field: ReportWin +0x5964 int  tech_row_even[4]   even-layout row y: tech_row_mid + (i-1)*(btn_h+16) - (btn_h+16)/2
// field: ReportWin +0x59A0 int  btn_w             0x96 in Datalinks mode; +0x59A4 btn_h 0x28; +0x59A8 card_w 0xAA
// field: Win +0xC4 Win* poParent
// field: Win +0xE0 char* pszCaption
// field: Win +0x13C RECT rRect1   window rect; with a client area ([+0x9C]&2): client rect relative to rRect2
// field: Win +0x14C RECT rRect2   position in the parent when [+0x9C]&2, else 0 (parent-local top = +0x140 + +0x150)
// field: Win +0x1A4 Win* apoChildren[150]
// field: Win +0x3FC int  iChildCount
// field: GraphicWin +0x444 Buffer oCanvas   (W @+0x4C4, H @+0x4C8 negative=top-down)
extern void SetupWin_ctor();                   // addr: 0x004AD880  observed  thiscall
extern void SetupWin_do_menu_rightside();      // addr: 0x004ADB70  observed  menu-strip layout (800/1024 literals)
extern void SetupWin_draw_item();              // addr: 0x004AE4D0  observed  per-item draw incl. decoration gate
extern void Console_init();                    // addr: 0x0051D890  observed  thiscall; GraphicWin_init(0,0,w,-h) main window + Win_set_def_focus
extern struct Console* Console_ctor(struct Console* self, int a2); // addr: 0x0050F460  observed  thiscall
extern void Console_on_post_redraw_nc_buffer(struct Console* self, struct Buffer* nc, int mode); // addr: 0x0050F960  thinker  thiscall; 4x Sprite_draw_2 connector tabs only
extern void Console_on_nc_hittest(struct Console* self, int x, int y); // addr: 0x0050F680  thinker  thiscall; HUD strip hit-test
extern void Console_on_nc_left_down();         // addr: 0x0050FB10  thinker  thiscall
extern void Console_on_nc_left_up();           // addr: 0x0050FE70  thinker  thiscall
extern void Console_on_nc_mouse_move();        // addr: 0x00510110  thinker  thiscall
extern void Console_update_data(struct Console* self, int a2); // addr: 0x00514880  thinker  thiscall; refreshes Econ/Psych/Labs/energy readouts
// ---- in-game MENU dropdown = a dedicated SPRITE-based console menu widget (NOT the universal Menu control; Menu_show never fires for it) ----
extern int  load_menu(int* self, int a2);      // addr: 0x00402F40  observed  thiscall; builds the MENU-button dropdown widget: Buffer_load_pcx menu2.pcx (menu.pcx if SW==800) + Sprite_extract_2 title 139x6 + 3x row 139x18 (key g_ui_transparency_key); GraphicWin_init(0,0,0x51,0x8f, parent=&MainWin_g); sets draw cbs g_menu_hilite_draw/g_menu_border_draw
extern void MenuWidget_layout_show(int* self); // addr: 0x004032A0  observed  fastcall this=param_1; SIZE+POSITION site: resize(w=[+0x441], h=[+0x44d]*[+0x286]+[+0x442]) via vtbl+0xc, then Win_move(x=(ScreenWidth-0x400)/2, y=(DAT_007af240-DAT_007af248)-h+ScreenHeight). NO popup_scale -> native-tiny; X hardcodes native-1024 centering = the mis-position
extern int  g_menu_hilite_draw(int self, int hot, int a3); // addr: 0x00403AF0  observed  =DAT_009b7b58; Buffer_box_sprite(self+0x474, DAT_78d960 +/- hilite) row-highlight/clip draw
extern int  g_menu_border_draw(int self);      // addr: 0x00403B70  observed  =DAT_009b7b5c; Buffer_box_sprite(self+0x474, DAT_78d960) border draw
extern struct GraphicWin g_console_menu_win;   // addr: 0x009380DC  observed  the MENU dropdown widget instance (static; parented to MainWin_g); +0x441 width(139) +0x442 topMargin(6) +0x44d rowH(18) +0x286 itemCount +0x474 draw Buffer +0x47c count
extern void MenuWidget_paint(/*ecx*/ int* self);  // addr: 0x00403340  observed  thiscall; the MENU dropdown painter: title strip (+0x10EC) then one row strip per item at [+0x1108] + k*[+0x1134] via Sprite_draw_2
// field: MenuWidget +0xA18 int item_count
// field: MenuWidget +0xA24 int hot_index   -1 = none
// field: MenuWidget +0xA3C char* item_text   item k at +0x14*k
// field: MenuWidget +0xA40 int item_flags   item k at +0x14*k
// field: MenuWidget +0x10EC struct Sprite strip_title   menu2.pcx 139x6
// field: MenuWidget +0x1118 struct Sprite strip_row   menu2.pcx 139x18
// field: MenuWidget +0x1144 struct Sprite strip_row2   menu2.pcx 139x18, 2nd row variant
// field: MenuWidget +0x1170 struct Sprite strip_row_hot   menu2.pcx 139x18, hot row
// field: MenuWidget +0x1108 int row0_y   the first row strip's y
// field: MenuWidget +0x1134 int row_pitch
// ---- in-game COMMLINK panel = a sibling sprite-based console widget (multi.pcx) ----
extern void commlink_win_build(int self);      // addr: 0x00479F90  observed  fastcall this=0x7FD648; builds the COMMLINK panel (multi.pcx sprites + 2 FlatButtons + GraphicWin_init_2(self+0xa38))
extern struct GraphicWin g_console_commlink_win; // addr: 0x007FD648  observed  the COMMLINK panel object (window embedded at base, Thinker: MultiWin); +0xa38 init rect +0xa40 w(0x8a) +0xa44 h +0x4c4 winW +0x4c8 -winH
extern void commlink_ctor(int self);           // addr: 0x0047A590  observed  thiscall; static-init ctor (stub 0x477E10), writes vtable
extern int  g_commlink_vtable;                 // addr: 0x0066C9F0  observed  COMMLINK panel vtable; +0x30 on_redraw stub 0x4798F0 +0x44 mouse_move +0x4c lclick +0x58 rclick
extern void commlink_redraw(int self, int a2); // addr: 0x00479330  observed  thiscall; full panel painter (7 faction-row loop + Council/VOTES + NO CONTACTS)
extern void commlink_draw_faction_row(int self, int faction, int row, int* rect); // addr: 0x00478630  observed  thiscall; one row: name (write_l_4) + status (write_right_l_6) + Spot_add
extern void commlink_on_mouse_move(int self, int x, int y); // addr: 0x00477E70  observed  thiscall; hover row via Spot_check -> [self+0x1168] -> repaint
extern void commlink_on_lclick(int x, int y);  // addr: 0x00477F30  observed  Spot_check: type1 -> commlink_attempt(faction), type2 -> time controls, type0 -> MP mute toggle
extern void commlink_on_rclick(int x, int y);  // addr: 0x00478150  observed  per-faction context Menu (talk/intel/call_council/renounce_pact/withdraw/chat)
extern void commlink_show(int* self);          // addr: 0x00479970  observed  fastcall; slide-in anim + Win_show; vcall +0x30 redraw first
extern void commlink_hide(int* self);          // addr: 0x00479C00  observed  fastcall; slide-out anim + Win_hide
extern void commlink_set_init_rect(int self);   // addr: 0x00479900  observed  thiscall; +0xa38 rect {0,0,0x8a,h}: h = 7 rowH + titleH + footerH (MP: + mpStripH + footerH + 0xE); sets 0x939ED8 bit 0x40
extern int  commlink_attempter(int a1, int a2); // addr: 0x005589E0  thinker  cdecl
extern void commlink_attempt(int faction);     // addr: 0x00558C60  thinker  cdecl; opens diplomacy with faction
extern int  Spot_check(void* self, int x, int y, int* spotPos, int* spotType); // addr: 0x005FAB00  thinker  thiscall
extern void Spot_kill_type(void* self, int type); // addr: 0x005FAA90  thinker  thiscall
// field: MultiWin +0xfdc  Sprite[3] btn_faces   121x18 idle/hover/pressed (stride +0x2c), shared by both FlatButtons
// field: MultiWin +0x1060 Sprite[3] mp_leds     14x14 MP talk/mute LEDs (stride +0x2c)
// field: MultiWin +0x10e4 Sprite    strip_title h=6
// field: MultiWin +0x1110 Sprite    strip_mp    h=0x1c
// field: MultiWin +0x113c Sprite    row_normal  h=0x12
// field: MultiWin +0x116c Sprite    row_hilite  h=0x12
// field: MultiWin +0x1144 byte      row_normal.key (= +0x113c+8; painter passes sprite+8 key byte -- pad rows reuse row_normal)
// field: MultiWin +0x1198 Sprite    strip_footer h=0x18
// field: MultiWin +0x1100 int       titleH      (6)
// field: MultiWin +0x1158 int       rowH        (0x12=18)
// field: MultiWin +0x11b4 int       footerH     (0x18=24)
// field: MultiWin +0x1168 int       hoverFaction (-1 = none)
// field: MultiWin +0x11c4 FlatButton council_btn  (buffer +0x444 = 0x7FEC50)
// field: MultiWin +0x1d10 FlatButton mp_btn       (MP-only, text Strings+0x440)
// field: MultiWin +0x285c Font      row_font     (=0x7FFEA4; Font_init(g_hud_font_name,10,0) @0x479FE4; runtime +0xC cell 13; set on buffer before rows + VOTES)
// field: MultiWin +0x2884 Font      hdr_font     Font_init(g_hud_font_name,14,1) @0x479FFA; MP header
// field: MultiWin +0xff4  int       btnW        (121)
// field: MultiWin +0xff8  int       btnH        (18)
// field: MultiWin +0x112c int       mpStripH    (28)
// field: MultiWin +0xa44  int       init_h      native panel height from commlink_set_init_rect (222 MP, 156 SP); device-scaled in place at build
// field: MultiWin +0x4c4  int       winW        device width (scaled at build); +0x4c8 = -winH
// field: MultiWin +0x28ac Spot      spots        (ctor 0x5FA860; row hit-rects, type1=contact row; rebuilt every repaint after Spot_kill_type 2/0/1)
// field: Spot +0x0 int* entries   0x18-byte slots
// field: Spot +0x4 int  capacity  Spot_init count
// field: Spot +0x8 int  count
// field: SpotEntry +0x0 int x0   +0x4 y0  +0x8 x1(excl)  +0xC y1(excl)  +0x10 type  +0x14 idx   Spot_check half-open, last-added wins
extern void commlink_draw_mp_header(int self, RECT* rect, int tick); // addr: 0x00478BE0  observed  thiscall RET 8; MP time widget: Spot_add(0, type 2) + time text via +0x2884 font + Buffer_write_cent_l_7
extern int g_mp_time_ticks;                                                    // addr: 0x007FFF7C  observed  commlink_draw_mp_header tick counter; bit 0 = blink phase
extern int g_mp_time_last_secs;                                               // addr: 0x007FFF78  observed  commlink_draw_mp_header: the seconds value last drawn
extern int g_mp_time_hold_depth;                                               // addr: 0x0093F664  guess     turn-timer hold nesting counter (inc/dec pairs 0x593054/0x593079, 0x513EB0/0x530475)
extern int g_mp_time_hold_ticks;                                               // addr: 0x0093F668  guess     turn-timer hold countdown, decremented per held tick @0x478CC3
extern int g_mp_time_hold_mask;                                                // addr: 0x0093E8E0  guess     per-player turn-timer hold bitmask
extern void commlink_spot_rect(void* spots, int idx, int type, RECT* rect); // addr: 0x0047A6F0  observed  thiscall RET 0xC; Spot_add(idx, type, L, T, R-L, B-T)
extern int  commlink_write_cent(struct Buffer* self, char* str, RECT* rect); // addr: 0x0047A720  observed  thiscall RET 8; Buffer_write_cent_l_7(str, rect, strlen); 0 on NULL str
// field: MultiWin +0xa24  int       expanded     MP: 0 -> MP strips at the panel bottom, faction rows skipped; also read by show/hide
extern void Console_menu_proc(struct Console* self, int a2); // addr: 0x0051BC70  thinker  thiscall; MENU-item SELECTION dispatcher (huge switch on item id -> editor/prefs/etc); NOT the opener
extern void Console_menu_daemon(int a1);       // addr: 0x0051D720  thinker  cdecl; forwards to Console_menu_proc (registered by Console_init @0x51d99d as the menu select callback)
extern void GraphicWin_resize(struct GraphicWin* self, int w, int h, int a4); // addr: 0x005D5540  thinker  thiscall; resizes the win buffer (Buffer_init) — the menu/panel sizing primitive; a4=1 repaints (vtbl+0x30) synchronously before returning
extern int  Win_move(struct Win* self, int x, int y); // addr: 0x005ED7D0  thinker  thiscall; moves a window to screen (x,y) = top-left
extern int  Win_resize(struct Win* self, int w, int h, int a4); // addr: 0x005ED880  thinker  thiscall RET 0xC; keeps top-left, repaints via vtbl+0x30 before returning
extern void Console_chat(struct Console* self, int a2); // addr: 0x00515770  thinker  thiscall; MP chat entry
extern int  Console_time_controls(struct Console* self); // addr: 0x00515900  thinker  thiscall; time-control widget
extern int  time_controls_dialog(struct Popup* p); // addr: 0x00589330  thinker  cdecl
extern void set_time_controls();               // addr: 0x00523C60  thinker
extern struct Console* MapWin_g;               // addr: 0x009156B0  thinker   Console instance = world map + HUD strip (len 0x247A4)
extern struct Console** MapWinPtr;             // addr: 0x007D3C3C  thinker   active console ptr
extern void MapWin_ctor();                     // addr: 0x004626E0  thinker  thiscall
extern void MapWin_init();                     // addr: 0x00470920  thinker  thiscall
extern void MapWin_init_2();                   // addr: 0x00470A90  thinker  thiscall
extern void MapWin_calculate_dimensions(struct Console* self); // addr: 0x00462980  thinker  thiscall; re-Font_inits the 3 map-label fonts on zoom change, size=min(12, zoom-derived); PRACX CMAIN_ZOOMPROCESSING_F calls this entry
extern void MapWin_draw_map(struct Console* self, int a2); // addr: 0x0046A550  thinker  thiscall
extern void MapWin_draw_base_names(struct Console* self); // addr: 0x00467DE0  thinker  thiscall; base name + "(production)" line via +0x1EEC8 font, landmark loop via +0x1EF20 font, text out Buffer_write_cent_l_8
extern void MapWin_on_redraw();                // addr: 0x0046B1D0  thinker  thiscall
extern int  MapWin_gen_map(struct Console* self, int faction, int units_only); // addr: 0x00469CA0  thinker  thiscall; renders the tile window under the current clip
extern void MapWin_gen_terrain_poly();          // addr: 0x004632D0  thinker  thiscall; per-tile terrain + overlay sprites at SCALE (zoom+16)/16
extern int  MapWin_pixel_to_tile(struct Console* self, int px, int py, int* tx, int* ty); // addr: 0x00463040  thinker  thiscall RET 0x10; 0 = on-map tile written, 1 = off-map/outside window
extern void MapWin_set_center(struct Console* self, int x, int y, int flag); // addr: 0x0046B1F0  thinker  thiscall; stores the centre tile, calls MapWin_draw_map
extern void Console_center(void);              // addr: 0x00515400  observed  cdecl; MapWin_set_center(map cursor x/y, 1); called by BaseWin_exit
extern int  MapWin_focus(struct Console* self, int x, int y); // addr: 0x0046B310  thinker  thiscall; nonzero = recentred an offscreen tile
extern void Console_focus(struct Console* self, int x, int y, int faction); // addr: 0x005108A0  thinker  thiscall; MapWin_focus over the 8 MapWinPtr slots
extern void Console_ready(struct Console* self);  // addr: 0x00510F50  thinker  thiscall; readies the selected unit, Console_focus on it unless PREF 0x80000 and it has orders
extern void MapWin_on_mouse_move(struct Console* self, int x, int y); // addr: 0x0046F000  thinker  thiscall RET 8; unit drag: path via MapWin_dest_line + "Move to" label on oWinBuffed
extern void MapWin_dest_line(struct Console* self, int x1, int y1, int x2, int y2, int veh_id, int faction, int mode, int a9, int a10, int a11, int a12); // addr: 0x00467430  thinker  thiscall RET 0x2C; mode 0: regions differ -> one straight MapWin_direct_dest_line @0x46794A (dist = (|dx|+|dy|)/2 * move_rate); else walks Path_find @0x467695 per tile drawing on-screen legs @0x467825; a failed Path_find, an unexplored tile or > 2*MapX steps -> the straight line;thinker  thiscall RET 0x2C; path hops -> MapWin_direct_dest_line
extern void MapWin_draw_radius(struct Console* self, int x, int y, int radius, int mode); // addr: 0x0046A2A0  thinker  thiscall RET 0x10; MapWin_gen_radius over the tiles within radius, the cursor diamond 0x7D3BE8 on the selected tile, then compute_clip + GraphicWin_soft_update_3 (+ do_all_draws when mode >= 2)
extern void MapWin_draw_radius_2(struct Console* self, int x, int y, int mode); // addr: 0x0046A530  thinker  thiscall; MapWin_draw_radius(x, y, 1, mode)
extern void MapWin_draw_cursor(struct Console* self);  // addr: 0x0046AD60  thinker  fastcall; MapWin_draw_radius(cursor, RADIUS 0, 2) when the cursor tile is in view (push 0 @0x46ADE4 -> 1 by uimod blinkfix)
extern void draw_cursor(void);                         // addr: 0x0046AE00  thinker  fastcall; every console: MapWin_draw_radius(cursor, RADIUS 0, 2) (push 0 @0x46AEBE -> 1 by uimod blinkfix), then TutWin_draw_arrow
extern void blink_timer(int);                          // addr: 0x0050EA40  thinker  cdecl timer cb; toggles g_blink_state, draw_cursor, edge-scroll on the mouse at the screen border
extern int  g_blink_state;                             // addr: 0x009392A8  observed  selected-unit blink phase (1 = hidden tick)
extern void MapWin_direct_dest_line(struct Console* self, int x1, int y1, int x2, int y2, int mode, int a7, int a8, int overlay); // addr: 0x004672C0  thinker  thiscall RET 0x20; overlay != 0 -> Buffer_line_2 on oWinBuffed @0x4673DC, else Buffer_line
extern void draw_my_dest(int veh_id);          // addr: 0x004B4BF0  thinker  cdecl; Go-To order line on oWinBuffed
extern void say_loc(char* buf, int x, int y, int a4, int a5, int a6); // addr: 0x00592250  thinker  cdecl
// field: Console +0x21A68 GraphicWin oWinBuffed   buffered overlay window (MapWin_g: 0x937118; canvas Buffer +0x444 = 0x93755C)
extern void MapWin_on_left_down(struct Console* self, int x, int y, int a3); // addr: 0x0046ED30  observed  thiscall; arms go_timer (333ms move mode / 1000ms view; Shift = go_timer(3) now)
extern void go_timer(int a1);                  // addr: 0x0050F170  observed  cdecl; enters goto-drag mode
extern void go_reset(void);                    // addr: 0x0050EF50  observed  cdecl; Win_hide(overlay), Time_stop(g_go_timer), cancels the drag; swallow_click=1 @0x50F0DC whenever g_go_win_idx>=0 (armed OR dragging)
extern int  Console_on_key_click(struct Console* self, int a2, int key); // addr: 0x005178C0  thinker  thiscall; only Alt filtered up front; unhandled keys reach go_reset @0x517ED6
extern int  g_go_win_idx;                      // addr: 0x0068A5CC  observed  MapWinPtr index of the armed goto drag, -1 idle
extern struct Time g_go_timer;                 // addr: 0x00939E60  observed  Time object for go_timer
// field: Console +0x1DD80 int goto_drag_active   1 while the goto line follows the mouse
// field: Console +0x1DD84 int goto_group         group-move label variant
// field: Console +0x1DD88 int swallow_click      MapWin_click returns at once when set; set by go_reset while g_go_win_idx>=0, CLEARED by MapWin_on_left_down (so it only eats a release whose press went elsewhere, or a release after a key-repeat go_reset)
// ---- map tile CLICK chain (MapWin_click = one handler for both buttons; see memory project-smac-mouse-scheme-proposals) ----
extern void MapWin_click(struct Console* self, int px, int py, int is_right); // addr: 0x0046D5D0  thinker  thiscall RET 0xC; locals [ebp-0x10]=tile x [ebp-0x14]=tile y [ebp-0x20]=Ctrl [ebp+0x10]=is_right; right: Ctrl+Shift=info @0x46E3A4, Shift=pref?cursor(0x46E463):menu(0x46E45C), plain gate @0x46E529 pref?menu:cursor+set_view(1); inline go-to @0x46DF0E needs eax=veh id (drag release: cursor_sprite 0x93AA9C)
extern void MapWin_on_left_click(struct Console* self, int px, int py); // addr: 0x0046EBA0  thinker  thiscall RET 8; vtbl+0x4C; this=Console+0x21A6C, -0x21A6C then MapWin_click(x,y,0) if g_map_mouse_enabled
extern void MapWin_on_left_double_click(struct Console* self, int px, int py); // addr: 0x0046EBD0  thinker  thiscall RET 8; vtbl+0x70; EMPTY (3 bytes); traced 2026-10-07: WM_LBUTTONDBLCLK is delivered (CS_DBLCLKS), then vtbl+0x50 and the release's vtbl+0x4C run as a second full click
extern void MapWin_on_right_click(struct Console* self, int px, int py); // addr: 0x0046EBE0  thinker  thiscall RET 8; vtbl+0x58 (fires on WM_RBUTTONUP); -> MapWin_click(x,y,1), which RETURNS at once (0x46D7E1 -> cleanup 0x46EAC4) while the go-to cursor / a pending action is set
extern void MapWin_on_right_down(struct Console* self, int px, int py); // addr: 0x0046EC10  thinker  thiscall RET 8; vtbl+0x5C; clears drag state; editor Ctrl+Shift/ScrollLock = right paint mode
extern void MapWin_on_left_up(struct Console* self, int px, int py); // addr: 0x0046EFF0  thinker  thiscall RET 8; vtbl+0x54; EMPTY
extern void MapWin_right_menu(struct Console* self, int tx, int ty, int dev_x, int dev_y); // addr: 0x0046C0D0  thinker  thiscall RET 0x10; builds/shows/dispatches the tile context Menu; item 1 'Move unit to here' = lock_veh, order 0x18, waypoint, synch_veh
extern void Console_activate(struct Console* self, int tx, int ty, int a4); // addr: 0x004D2F00  thinker  thiscall RET 0xC; activates the unit(s) on a tile (veh_pick for a stack)
extern void Console_set_view(struct Console* self, int force); // addr: 0x00511480  thinker  thiscall RET 4; leave move mode (+0x23BD8=0) and redraw
extern void Console_set_move(struct Console* self, int force); // addr: 0x00511520  thinker  thiscall RET 4; enter move mode (+0x23BD8=1) for selected_veh, Console_focus on it
extern int  Console_set_cursor(struct Console* self, int tx, int ty); // addr: 0x005147E0  thinker  thiscall RET 8; moves the map cursor (Console_cursor_next) and redraws it; 1 = off-map
extern void Console_go_to(struct Console* self, int veh_id, int a3, int a4); // addr: 0x004D61A0  thinker  thiscall RET 0xC; interactive go-to (base/route popups)
extern int  Console_selected(struct Console* self); // addr: 0x005107E0  thinker  thiscall; pending cursor-action code (0 none; 2/3 road-to, 4 airdrop, 8 patrol, 10 arty, 11 bombing run)
extern int  Console_selecting(struct Console* self, int tx, int ty); // addr: 0x005105C0  thinker  thiscall RET 8; per mouse-move: 1 = draw the drag line, sets the target/invalid cursor from +0x23D10
extern void Console_cursor_on(struct Console* self, int a2); // addr: 0x00510400  thinker  thiscall; Win_set_cursor(g_cursor_sprites[i], g_cursor_hot_x[i], g_cursor_hot_y[i])
extern int  Console_edit_lock(void); // addr: 0x004E1F40  thinker  cdecl; 1 = scenario editor with ScrollLock / GameState&0x8000000
extern int  NetDaemon_lock_veh(struct AlphaNet* self, int* veh_id, int a3, int a4, int a5, int a6); // addr: 0x00531020  thinker  thiscall RET 0x14; this=0x93CD90; 0 = locked
extern void NetDaemon_unlock_veh(struct AlphaNet* self); // addr: 0x005310F0  thinker  thiscall; this=0x93CD90
extern int  netconnect_join(int self);          // addr: 0x004E2E50  observed  thiscall; JOIN path: #NETCONNECT_JOIN name, enum sessions, 0 found -> #NETCONNECT_SESSION_NOT_FOUND (Try Again loops), else #NETCONNECT_SESSIONS picker
extern int  AlphaNet_enum_sessions(struct AlphaNet* self, void* list, char* password); // addr: 0x0062E420  observed  thiscall RET 8; this=0x93CD90; IDirectPlay::EnumSessions (vtbl+0x34, DPENUMSESSIONS_AVAILABLE, default timeout, callback 0x630C30)
extern int  AlphaNet_enum_sessions_cb();       // addr: 0x00630C30  observed  stdcall; EnumSessions callback, appends to the list in 0x9BE4E8
extern void synch_veh(int veh_id); // addr: 0x00593220  thinker  cdecl
extern void StatusWin_set_loc(struct StatusWindow* self, int tx, int ty); // addr: 0x004B9F90  thinker  thiscall RET 8; 'Info on this square' (Ctrl+Shift+right click; also from StatusWin_redraw)
extern int  g_map_mouse_enabled;               // addr: 0x0090D938  observed  nonzero = the map window accepts mouse clicks (gate of every MapWin_on_* handler)
extern int  GamePreferences;                   // addr: 0x009A6490  thinker   PREF_* bits (0x1000 mouse-edge scroll, 0x80000 no centre on units with orders, 0x8000000 animated slide windows)
extern int  GameMorePreferences;               // addr: 0x009A6494  thinker   MPREF_* bits (0x100 right-click pops up menu, 0x400 detailed right-click menus, 0x40000 click on unit cancels orders, 0x4 zoom-to-base no recentre)
extern int  ControlTurnC;                      // addr: 0x0093A938  thinker   nonzero = not the human's turn (map input locked)
extern void* g_console_win_vtbl[];             // addr: 0x0066EC18  observed  Console oMapWin GraphicWin vtable (entries are vbase adjustor thunks 0x51DExx -> MapWin handlers); +0x44 mouse_move +0x48 mouse_leave (stub 0x404260; Win_OnMouseMove calls it on a mouse-window change) +0x4C left_click +0x50 left_down +0x54 left_up +0x58 right_click +0x5C right_down +0x64 key_click +0x70 left_double_click +0x144 l_button_down +0x148 l_button_up +0x14C r_button_down +0x150 r_button_up
extern void Win_on_r_button_down(struct Win* self, int is_double, int x, int y, unsigned a5, int is_left); // addr: 0x005F6710  thinker  thiscall; vtbl+0x14C; is_double (WM_RBUTTONDBLCLK) -> vtbl+0x74; then vtbl+0x5C right_down
extern int  WinProc_forward(void* hWnd, unsigned Msg, unsigned wParam, int lParam); // addr: 0x005D5C50  observed  stdcall RET 0x10; handles WM_SIZE/WM_SETCURSOR itself, else CallWindowProcA(WinProc); the imm32 @0x5D5C70 is PRACX's WinProc redirect slot
// field: Console +0x1DD78 int map_win_idx        this console's MapWinPtr slot: 0 = main map, 1 = secondary map window (gets the 'Recenter this window' menu)
// field: Console +0x1DD8C int editor_paint_mode  scenario editor terrain paint: 1 = left button, 2 = right button
// field: Console +0x1EF4C void* cursor_sprite    current map cursor sprite; 0x93AA9C = go-to target (set by go_timer), 0x93AB4C = invalid target, 0 = arrow
// field: Console +0x1EF50 int cursor_id          0x7F00 = IDC_ARROW
// field: Console +0x23BD8 int fUnitNotViewMode  (= 0x939288) nonzero = a unit awaits orders (MOVE mode); 0 = VIEW mode (left click moves the map cursor)
// field: Console +0x23D10 int selecting_mode    (= 0x9393C0) go_timer sets 1 (goto drag) / 9 (Ctrl drag in view mode, or base-route flag 0x40000); 8 = patrol target; Console_selecting keys the cursor on it
// field: Console +0x23D1C int group_formed      (= 0x9393CC) Console_group sets 1 (0x4D95CC / 0x4D9676), cleared 0x50F650; go_timer keeps mode 1 and sets goto_group; MapWin_click 0x46DDA7 veh_fake group go-to
// field: Console +0x23D14 int selecting_range   max tile distance for the selecting_mode target, -1 = unlimited
extern int  veh_find(int x, int y, int faction, int a4);   // addr: 0x005C0CB0  thinker  cdecl; a4 = -1; unit of faction on the tile or -1
extern int  veh_selectable(int veh_id);                    // addr: 0x005C1A20  thinker  cdecl; nonzero = the human may select/order it
extern void Time_stop(struct Time* self);                   // addr: 0x00616780  observed  thiscall; KillTimer / timeKillEvent (go_reset's second call, this=g_go_timer)
extern void* g_go_cursor_sprite;                            // addr: 0x0093AA9C  observed  the go-to target cursor sprite go_timer installs (Console+0x1EF4C == this while a drag is live)
// field: Console +0x23D94 GraphicWin oMapWin   the Console's own GraphicWin (MapWin_g: 0x939444; vtable g_console_win_vtbl); its vtable entries are vbase thunks that subtract 0x2328 to reach the handlers' this = Console+0x21A6C
// field: Console +0x1DE0C int drag_last_tile_x   last tile the drag line was drawn for (+0x1DE10 y); -1 = redraw on the next move
// field: Console +0x1DD70 uint map_win_flags     bit 0x40000 = base-route window (left press needs a base), bit 0x40000000 = double set_center on base zoom
extern RECT RenderTileBounds;                  // addr: 0x007D3C28  thinker   visible tile rect
extern POINT g_map_cursor_diamond[4];          // addr: 0x007D3BE8  observed  selected-unit cursor polygon; MapWin_draw_map's scroll path shifts it with the canvas
// field: Console +0x1DDA4 int map_tile_left    top-left view tile x
// field: Console +0x1DDA8 int map_tile_top     top-left view tile y
// field: Console +0x1DDAC int map_pixel_left   sub-tile / letterbox pixel offset x
// field: Console +0x1DDB0 int map_pixel_top    sub-tile / letterbox pixel offset y
// field: Console +0x1DDCC int map_tiles_odd_x  visible half-columns, odd rows
// field: Console +0x1DDD0 int map_tiles_odd_y
// field: Console +0x1DDD4 int map_tiles_even_x
// field: Console +0x1DDD8 int map_tiles_even_y
// field: Console +0x21A44 int drawOnlyCursor   nonzero = MapWin_draw_map scroll-blits instead of a full redraw
// field: Console +0x21A48 RECT map_strip_rect_a   exposed-strip tile rect, horizontal move
// field: Console +0x21A58 RECT map_strip_rect_b   exposed-strip tile rect, vertical move
// field: Console +0x1DD98 int map_zoom_idx   current map zoom index (dword idx 0x7766); draw_support fit loop writes 2..-15 via BaseWin+0x3C40C, MapWin_init_2 seeds -7/-8; tile w = (800+50*idx)/16 when g_map_zoom_num unarmed
// field: Console +0x1DD9C int map_center_x   map view center tile x (BaseWin+0x3C410 in draw_support)
// field: Console +0x1DDA0 int map_center_y   map view center tile y (BaseWin+0x3C414)
// field: Console +0x1EEC0 int map_label_zoom_cache   last-zoom gate for the 3 map-label Font_inits (cmp [0x7766] copy)
// field: Console +0x1EEC8 struct Font map_label_font_s0   base-name/production map labels, style 0
// field: Console +0x1EEF0 int map_label_font_s0_size      native-units size cache for +0x1EEC8
// field: Console +0x1EEF4 struct Font map_label_font_s1   style-1 map label font
// field: Console +0x1EF1C int map_label_font_s1_size      native-units size cache for +0x1EEF4
// field: Console +0x1EF20 struct Font map_label_font_s2   landmark map labels, style 2
// field: Console +0x1EF48 int map_label_font_s2_size      native-units size cache for +0x1EF20
extern struct StatusWin* StatusWin_g;          // addr: 0x008C5568  thinker   left unit/status + tile-info panel of the HUD
extern void StatusWin_ctor();                  // addr: 0x004BA1A0  thinker  thiscall
extern void StatusWin_init();                  // addr: 0x004B9FC0  thinker  thiscall
extern void StatusWin_draw();                  // addr: 0x004B8830  thinker  thiscall
extern void StatusWin_on_redraw();             // addr: 0x004B8890  thinker  thiscall; = pfncDrawTileInfo; PRACX calls entry+3 (0x4B8893) directly -- NEVER hook/patch the first 5 bytes
extern void StatusWin_draw_active(struct StatusWin* self, int veh_id, int mask, int a4); // addr: 0x004B4CF0  thinker  thiscall; active-unit box
extern int  StatusWin_redraw(struct StatusWin* self); // addr: 0x004B9EA0  thinker  thiscall; repaints the HUD unit/tile panels
extern void StatusWin_draw_status();           // addr: 0x004B6570  thinker  thiscall; tile-info yields
extern struct GraphicWin InfoWin;              // addr: 0x007AD2A0  thinker   box-5 typewriter-ticker window (readout text)
extern struct ReportInfc* ReportIf;            // addr: 0x00885F38  thinker   bottom-console report interface controller
extern void* ReportIf_vtbl;                    // addr: 0x0066D700  observed  SubInterface-shape 19 slots (ctor 0x4AD170 installs; 0x66D590 belongs to Holobook, NOT ReportIf)
extern void ReportIf_on_button_clicked(int id); // addr: 0x004A6330  thinker  thiscall RET 4; ReportIf vtbl+0x34; id switch (kind tabs 2..8, faction 10000+f, cases 0xCEF.., >0x270F units)
extern void ReportIf_on_event(int type, int a2, int param); // addr: 0x004A6D70  observed  thiscall RET 0xC; ReportIf vtbl+0x40; param 0x3EE/0x3EF -> WorldWin_set_world/detail_map; type 2 0x92/0x93 -> +0x1E1D8
extern struct WorldWindow* WorldWin;           // addr: 0x008E9F60  thinker   lower-right minimap world-map window
extern void WorldWin_set_detail_map(struct WorldWindow* self); // addr: 0x004C3950  thinker  thiscall; mode=1, flips btn group, tail-jmp Win_hide(WorldWin)
extern void WorldWin_set_world_map(struct WorldWindow* self); // addr: 0x004C3990  thinker  thiscall; mode=0, flips btn group, Win_show(WorldWin,0)
extern void WorldWin_hide_all(void);                     // addr: 0x004C3A40  thinker   no args
extern void WorldWin_show_all(struct WorldWindow* self); // addr: 0x004C39D0  thinker  thiscall; re-applies current mode
extern void WorldWin_on_redraw(struct WorldWindow* self); // addr: 0x004C3EC0  observed  thiscall; minimap render; fit-check +0xa14/+0xa18 buf vs +0x4c4/+0x4c8 win (center 1:1 else stretch); calls WorldWin_draw_box
extern void WorldWin_draw_box(struct WorldWindow* self); // addr: 0x004C4630  observed  thiscall; draws the white viewport rectangle on the minimap; gated on g_view_w!=0 (native also &&g_scroll_susp1==0&&g_scroll_susp2==0)
extern void Win_show(struct Win* self, int a2); // addr: 0x005ED9D0  thinker  thiscall
extern void Win_hide(struct Win* self);        // addr: 0x005EDCD0  thinker  thiscall
extern int  WinProc(void* hWnd, unsigned Msg, unsigned wParam, int lParam); // addr: 0x005F0650  thinker  stdcall RET 0x10; game WndProc (PRACX subclasses + forwards here)
extern struct Win* Win_get_active_target(void);  // addr: 0x005F6A50  observed  cdecl no-args; modal top [0x9B7AE0] (basepop [0x9B8D7C] overrides) else [0x9B7AC4]/[0x9B7AEC] -> caches [0x9B7AC8] -> ->[0xA8] key target; WinProc WM_KEYDOWN call @0x5F07B0, WM_KEYUP @0x5F07F0 (wParam [esp+0x64], lParam [esp+0x68] in WinProc's frame)
extern int  Win_on_char(/*ecx*/ struct Win* self, int ch, int composite); // addr: 0x005F5FB0  observed  thiscall; vtbl+0x13C of every Win; WM_CHAR dispatch (WinProc @0x5F083D on Win_get_active_target)
extern int  Win_key_default(/*ecx*/ struct Win* self, int composite, int key); // addr: 0x005EEA90  observed  thiscall RET 8; generic per-window key handler: Enter/Esc -> vtbl+0xB0(-1/-2), then the +0x42C callback, vtbl+0x64 on_key, the +0x38 chain
extern void* InterludeWin_vtbl[];              // addr: 0x0066C708  observed  InterludeWin vtable (ctor store @0x45F2C0); +0x50 InterludeWin_on_lclick, +0x64 0x406A80 stub, +0x68 InterludeWin_on_keydown, +0xB0 0x404270 stub, +0x138 Win_on_key, +0x13C Win_on_char
extern int  InterludeWin_on_keydown(/*ecx*/ struct InterludeWin* self, int vk, int composite); // addr: 0x0045F6F0  observed  thiscall; vtbl+0x68; Win_release_modal then return 1 -- any key closes the interlude
extern int  InterludeWin_on_lclick(/*ecx*/ struct InterludeWin* self); // addr: 0x0045F700  observed  thiscall; vtbl+0x50; Win_release_modal then return 1
extern int  Win_key_dispatch(/*ecx*/ struct Win* self, int composite, int key); // addr: 0x005EEB90  observed  thiscall; focus children, then MapVirtualKeyA(vk,2): a char-producing key skips Win_key_default and goes to vtbl+0x68
extern void Win_drain_chars(void);             // addr: 0x005FCFE0  observed  cdecl; PeekMessageA(WM_CHAR, PM_REMOVE) + Translate + Dispatch loop at Win_on_key's tail -- the keystroke's WM_CHAR is dispatched inside the key-down's dispatch
extern void Win_pump_modal(void);              // addr: 0x005FC700  observed  cdecl; PeekMessageA(0..0x400, PM_REMOVE) + Translate + Dispatch; Win_set_modal's loop body
extern int  Win_repost_syskey(/*ecx*/ struct Win* self, int vk, int composite); // addr: 0x005F6230  observed  thiscall; vtbl+0x140; WM_SYSKEYDOWN -> re-posts a plain WM_KEYDOWN + DefWindowProc
extern int  App_on_key_message(/*ecx*/ struct Win* self, int vk, int is_down, int repeat, int scan); // addr: 0x005F5D10  observed  thiscall; vtbl+0x138 of every Win; folds SHIFT/CTRL/ALT into vk bits 0x10000/0x20000/0x40000 -> [0x9B7B18]; lParam halves never read
extern struct Win* g_modal_top;                 // addr: 0x009B7AE0  observed  modal-window top (sole write Win_set_modal 0x5EE190 @0x5EE1C8); the picker during PartPicker_exec/ProdPicker_exec
extern int  SetupWin_do_menu_2(struct SetupWin* self, struct Popup* popup, int a3, int a4); // addr: 0x004ADB20  thinker   thiscall RET 0xC; stores popup at +0x1014, runs SetupWin_do_menu_rightside; returns reply index or -1
extern int  SetupWin_do_menu(struct SetupWin* self, const char* label, int a3, int a4);      // addr: 0x004ADAF0  thinker   thiscall RET 0xC; text-file variant of the strip menu (+0x1014 stays 0)
extern void SetupWin_on_left_click(struct SetupWin* self, int x, int y);      // addr: 0x004AE340  thinker   thiscall; vtbl+0x4C; Spot_check hit -> Win_release_modal
extern int  SetupWin_on_key_click(struct SetupWin* self, int a2, int key);    // addr: 0x004AE3E0  thinker   thiscall; vtbl+0x64; 0x0D release, 0x1B sel=-1 + release, 0x26/0x28 move highlight
extern void SetupWin_on_mouse_move(struct SetupWin* self, int x, int y);      // addr: 0x004AE380  thinker   thiscall; vtbl+0x44
extern void* SetupWin_vtbl[];                                                 // addr: 0x0066D8E8  observed  SetupWin vtable (SetupWin_ctor @0x4AD957); +0xE4 Win_set_modal +0xE8 Win_release_modal +0xEC Win_modal_always
// field: SetupWin +0xFCC  int  item_count      strip item count (popup Dialog+0x10 or parsed #lines)
// field: SetupWin +0xFD0  int  sel_index       highlighted item; -1 after ESC; the value do_menu_rightside returns (top_menu: <0 or 6 = exit)
// field: SetupWin +0x1010 struct Dialog* items_dialog   popup's Dialog sub-object
// field: SetupWin +0x1014 struct Popup* menu_popup     set by SetupWin_do_menu_2 for its duration, else 0
// field: SetupWin +0x1118 struct Buffer strip_buf      openitem.flc strip frames (Flic-decoded, 354x75)
// field: SetupWin +0x1198 int  strip_w         strip_buf+0x80; 354 from the openitem.flc header
// field: SetupWin +0x119C int  strip_h_neg     strip_buf+0x84; -75 (top-down)
// field: SetupWin +0xA1C struct Buffer* deco[3]   per-item decoration art (custom_planet previews; NULL on other menus)
// field: SetupWin +0xA28 int  deco_x[3]       decoration dst x (800: 449, else ScreenWidth-srcW; moons 0)
// field: SetupWin +0xA34 int  deco_y[3]       decoration dst y (800: -168, else 0; moons 0)
extern void Console_on_sys_close(void);                                       // addr: 0x0051D7C0  thinker   sets ControlTurnA=1 (window X / SC_CLOSE path)
extern void Console_human_turn(struct Console* self);                         // addr: 0x00514050  thinker   thiscall; human turn entry + input pump; 4 E8 sites 0x527661 0x52826E 0x5282C9 0x52A765
extern int  Console_veh_turn(struct Console* self);                           // addr: 0x00513B90  thinker   thiscall; selected-unit input pump; exits on ControlTurnA
extern void Console_retire_game(void);                                        // addr: 0x00514B30  thinker   REALLYRETIRE confirm; sets ControlTurnA=1, ControlTurnB=!MP
extern void Console_set_preferences(void);                                    // addr: 0x00514EF0  thinker   -> PrefWin_show(PrefWin_g, 0)
// field: Console +0x23BDC int  selected_veh     -1 = none
// field: Console +0x23BE4 int  input_pump_live  (= 0x939294) 1 while Console_human_turn/Console_veh_turn sit in wait_loop; blink_timer draws the unit cursor only while set (uimod hudsync detours Console_veh_turn's entry 0x513B90 to sync StatusWin's info tile)
// field: Console +0x23BE8 int  turn_live        1 from Console_human_turn entry; 0 = end turn
extern int  g_console_active;                                                 // addr: 0x0093A940  observed  set 1 at Console_human_turn entry; Console_menu_proc returns early when 0
extern int  g_menu_cmd_pending;                                               // addr: 0x0093A944  observed  set 1 by Console_menu_proc when refused (g_console_active==0)
extern struct Win* g_active_key_target;         // addr: 0x009B7AC8  observed  Win_get_active_target's resolved target, refreshed per key
extern int  g_key_vk_composite;                 // addr: 0x009B7B18  observed  vk | modifier bits; pushed as on_key arg2 @0x5F61D7/0x5F61FE/0x5F6211
extern void Win_add_child(/*ecx*/ struct Win* self, struct Win* child); // addr: 0x005F5200  observed  thiscall RET 4; flags&0x2000000 -> append to apoChildren[+0x1A4] (count +0x3FC) else insert at 0; no static callers
extern int  ScrollBar_on_key(/*ecx*/ struct ScrollBar* self, int key, int vk); // addr: 0x00606560  observed  thiscall RET 8; vtbl+0x64; parent NULL -> 0; vertical: PGUP/PGDN value -+[+0xA40]; horizontal: END/HOME; notifies parent vtbl+0xC0(id,value); only reached via Win +0x43C/+0x440 (heap bars, style flag 8)
// field: ScrollBar +0xA1C int border_color   -1 = none;  +0xA64 int fill_color (7);  +0xA68 int bevel_count (2);  +0xA6C/+0xA70 int bevel_colors (255/248);  +0xA74 Sprite* grip (NULL = none);  +0xA78 Sprite* trough_tile (NULL = flat)   (ScrollBar_draw 0x6066F0 has no disabled state)
extern void ScrollBar_on_mouse_move(/*ecx*/ struct ScrollBar* self, int x, int y); // addr: 0x00605D90  observed  thiscall RET 8; vtbl+0x44; the thumb-drag path (gated on g_pressed_win_l == self)
extern void ScrollBar_on_chevron_timer(/*ecx*/ struct ScrollBar* self, int btn_id); // addr: 0x006069A0  observed  thiscall RET 4; vtbl+0xA4; the arrow's OWN repeat timer notifies here (the arrow release -> vtbl+0xB0)
extern void BaseButton_set_bubble_text(/*ecx*/ struct FlatButton* self, const char* text); // addr: 0x00607550  observed  thiscall RET 4; strdup's into +0xA80 (nullptr clears); hover (0x608500) shows it after 1000 ms
// field: FlatButton +0xABC int label_color[3]   per draw state idle/hover/pressed, -1 = keep the buffer colour; +0xA80 char* bubble_text; FlatButton press (0x6075DD) calls Win_clear_bubble_text unconditionally
extern void ScrollBar_on_chevron(/*ecx*/ struct ScrollBar* self, int btn_id); // addr: 0x00606B20  observed  thiscall RET 4; vtbl+0xB0; parent NULL -> return; btn 1 = value-- (>= +0xA20), 2 = value++ (<= +0xA24); parent vtbl+0xC0(id +0xA18, value); optional cb +0x2144; own redraw vtbl+0xF8
extern void ScrollBar_on_chevron_repeat(/*ecx*/ struct ScrollBar* self, int btn_id); // addr: 0x006069A0  observed  thiscall RET 4; vtbl+0xA4; held-chevron auto-repeat (timer +0xA38/delay +0xA30), notifies parent vtbl+0xC4
extern void Win_OnLButtonDown(void* a1, int is_double, int x, int y, unsigned a5); // addr: 0x005F2330  thinker  cdecl; WM_LBUTTONDOWN (is_double=0) / WM_LBUTTONDBLCLK (1) -> Win_get_mouse_window -> vtbl+0x144
extern void Win_on_l_button_down(struct Win* self, int is_double, int x, int y, unsigned a5, int is_right); // addr: 0x005F63C0  thinker  thiscall; vtbl+0x144; is_double (WM_LBUTTONDBLCLK) -> vtbl+0x70 first; then Win_left_down_event -> vtbl+0x50
extern void Win_left_down_event(struct Win* self, int a2, int a3, int a4); // addr: 0x005EE750  thinker  thiscall; button delivery; entry vetoes [+0x98]&0x200000 and [+0x9C]&8
extern int  Win_on_nc_hittest(struct Win* self, int x, int y); // addr: 0x005F5AD0  thinker  thiscall; vtbl+0x12C default; 2=title-drag, 0xA..0x11=edges
extern int  Win_get_mouse_window(int* x, int* y); // addr: 0x005F6F10  thinker  cdecl; resolves window under screen coords, rewrites coords window-local
extern struct Win* get_mouse_window_recurse(struct Win* w, int* x, int* y); // addr: 0x005F6AB0  thinker  cdecl; hit-test; a window with +0x98 & 0x10000000 declines a see-through pixel
extern int  g_mouse_raw_x;                     // addr: 0x009B6628  observed  the event's screen x (stored by Win_get_mouse_window)
extern int  g_mouse_raw_y;                     // addr: 0x009B662C  observed  the event's screen y
extern struct Win* g_top_windows[];            // addr: 0x009B6E48  observed  top-level window list Win_get_mouse_window walks
extern int  g_top_window_count;                // addr: 0x009B7B34  observed  entries in g_top_windows
extern void Win_OnMouseMove(void* a1, int x, int y, unsigned a4);        // addr: 0x005F2290  thinker  cdecl; WM_MOUSEMOVE -> Win_get_mouse_window -> Win_on_mouse_move
extern void Win_OnLButtonUp(void* a1, int x, int y, unsigned a4);        // addr: 0x005F2570  thinker  cdecl; WM_LBUTTONUP
extern void Win_OnRButtonDown(void* a1, int a2, int x, int y, unsigned a5); // addr: 0x005F25C0  thinker  cdecl; WM_RBUTTONDOWN
extern void Win_OnRButtonUp(void* a1, int x, int y, unsigned a4);        // addr: 0x005F2620  thinker  cdecl; WM_RBUTTONUP
extern void Win_on_mouse_move(struct Win* self, int x, int y, int a4);   // addr: 0x005F6320  thinker  thiscall RET 0x10; window-local device x,y; vtbl+0x44 call @0x5F636B
extern void Win_forward_mouse_move(/*ecx*/ struct Win* self, int x, int y, int a4); // addr: 0x005EE4D0  observed  thiscall; skips flags +0x98&0x200000 / +0x9C&8; calls [+0x408](x,y) then vtbl+0x44(x,y) with x,y UNCHANGED
extern struct Buffer g_sprite_load_scratch;    // addr: 0x009B6080  observed  Buffer a filename-backed Sprite ([+0]=name) is loaded into by Sprite_blit_scaled_core @0x5E4BC8 (Buffer_load_pcx)
extern void Win_on_l_button_up(struct Win* self, int x, int y, int a4, int a5); // addr: 0x005F6550  observed  thiscall; vtbl+0x148; in_box_2 gate {0,0,winW,winH} then vtbl+0x4C(x,y)
extern void Win_on_r_button_up(struct Win* self, int x, int y, int a4, int a5); // addr: 0x005F6880  observed  thiscall; vtbl+0x150; in_box_2 gate then vtbl+0x58(x,y)
extern int  in_box_2(int x, int y, RECT* box);                            // addr: 0x005FA7E0  thinker  cdecl
extern void Win_screen_to_client_2(int* x, int* y);                       // addr: 0x005ED2D0  thinker  cdecl
extern void Win_do_tracking(struct Win* self, int x, int y); // addr: 0x005F7580  thinker  thiscall; WM_MOUSEMOVE drag/stash drain when g_mouse_stash_win set
extern int  Win_update_cursor(struct Win* self, int a2); // addr: 0x005F1820  thinker  cdecl
extern int  Win_set_cursor(struct Win* self, struct Sprite* sprite, int hx, int hy); // addr: 0x005EC740  thinker  thiscall RET 0xC; Win +0x188 sprite, +0x18C/+0x190 hotspot
extern void recurse_zorder(struct Win* w);     // addr: 0x005F4EC0  thinker  cdecl
extern int  g_mouse_stash_type;                // addr: 0x009B7AA8  observed  nc-hit code stashed by Win_OnLButtonDown
extern struct Win* g_mouse_stash_win;          // addr: 0x009B7AAC  observed  nonzero routes WM_MOUSEMOVE to Win_do_tracking
extern int  g_mouse_stash_x;                   // addr: 0x009B7AB0  observed
extern int  g_mouse_stash_y;                   // addr: 0x009B7AB4  observed
extern struct Win* g_last_mouse_win;           // addr: 0x009B7A7C  observed  last resolved hover window (enter/leave source)
extern struct Win* g_last_pressed_win;         // addr: 0x009B7AB8  observed  set on SC 0xF060 syscommand path
extern void* g_pressed_win_l;                  // addr: 0x009B7ACC  observed  WINDOW ptr pressed by left button (Win_on_l_button_down; the old "g_click_x" reading was WRONG — ScrollBar_on_mouse_move cmp's it vs this); CLEARED by Win_close/Win_hide when they match the closing window
extern void* g_pressed_win_r;                  // addr: 0x009B7AD0  observed  right-button twin (Win_on_r_button_down); same clear
extern int  g_click_pending;                   // addr: 0x009B7AD4  observed  =1 at button-down; drag/track handlers gate on it
extern void* g_sb_track_win;                   // addr: 0x009B7ABC  observed  mouse-capture window: Win_get_mouse_window routes every event to it while shown (set by ScrollBar/FlatButton press, go_timer, editor paint presses; cleared by FlatButton release, Win_set_modal, Win_close/Win_hide, go_reset for an armed/dragging map)
extern void MapWin_on_track_end(void);          // addr: 0x0046EB90  observed  thiscall; Win vtbl+0x10 of the map's GraphicWin (adjustor 0x51DE30); jmp go_reset
// field: Win vtbl +0x10 void on_track_end()   called after g_sb_track_win is cleared (go_reset, FlatButton release, Win_set_modal, Win_hide)
extern int  g_sb_track_phase;                  // addr: 0x009B7AC0  observed  repeat-track phase/delay counter paired with g_sb_track_win
// field: WorldWindow +0x239CC int detail_mode   1 = detail map shown (WorldWin hidden)
// field: ReportInfc +0x1E1D8 int event_flag_92  set 1/0 by ReportIf_on_event type 2 param 0x92/0x93
extern struct SubInterface* MainWinIface;      // addr: 0x007AF234  observed  = MainWin+0xA14; iface subobject (vtbl 0x66C3D4)
extern void MainWinIface_on_event(int type, int a2, int id); // addr: 0x0045CCB0  observed  thiscall RET 0xC; vtbl+0x1B0; id-0x3E8: 6->set_world_map 7->set_detail_map; type2->MapWin, type3->0x45B550
extern struct BattleWindow BattleWin;                                          // addr: 0x006EEED8  thinker   combat console sub-interface (iface mode 10)
extern void BattleWin_init(/*ecx*/ struct BattleWindow* self);                 // addr: 0x004219E0  thinker   fastcall; derives the 8 rects from MainWin seeds D80/DC0
extern void BattleWin_battle_report(/*ecx*/ struct BattleWindow* self, int attVeh, int defVeh, int a4, int a5, int flags); // addr: 0x00421B50  thinker   thiscall RET 0x14; paints the combat console into the strip buffer
extern void BattleWin_clear(/*ecx*/ struct BattleWindow* self);                // addr: 0x00422C50  thinker   fastcall; redraws the 4 d528 boxes
extern void BattleWin_on_status(/*ecx*/ struct BattleWindow* self, int enter); // addr: 0x00422CC0  thinker   thiscall RET 4; enter: slide_show(0,2), leave: slide_hide(0,2)
// field: BattleWindow +0x30 RECT rcUnitL   left unit box (DC0 +4 inset, left half)
// field: BattleWindow +0x40 RECT rcUnitR   right unit box
// field: BattleWindow +0x50 RECT rcPortraitL   left portrait box (D80 +4 inset, left half)
// field: BattleWindow +0x60 RECT rcPortraitR   right portrait box
// field: BattleWindow +0x70 RECT rcLeftPanel   copy of MainWin seed D80
// field: BattleWindow +0x90 RECT rcBigCentre   copy of MainWin seed DC0
extern void* BattleWin_iface_vtbl[];                                           // addr: 0x0066AA44  observed  slot 0 = BattleWin_on_status
extern struct BattleWindow* g_battlewin_ptr;                                   // addr: 0x007AE818  observed  written by BattleWin_init
extern struct Sprite g_faction_portrait_sprites[];                             // addr: 0x0078EDF0  observed  stride 0x65C per faction id; 96x115, 1-row scanline dither
extern void BattleWin_pulse_timer(/*ecx*/ struct BattleWindow* self);          // addr: 0x00421B20  thinker   Time_pulse(timer_callback_daemon_2, 0, 5000, 5)
// field: InfoWin +0xAC int suspended   nonzero stops the typewriter tick
extern struct Sprite g_console_centre_sprite;                                // addr: 0x007D1750  observed  normal centre-console art drawn 1:1 by slide_hide flag-2 tail @0x45DDF8
extern void BattleWin_on_iface_button_clicked(int id); // addr: 0x00422DC0  thinker  thiscall RET 4; vtbl+0x1A4; forwards to MainWinIface
extern void BattleWin_on_iface_group_clicked(int type, int a2, int id); // addr: 0x00422DE0  thinker  thiscall RET 0xC; vtbl+0x1B0; type==1 -> release_iface_mode + MainWinIface_on_event
extern void SubInterface_release_iface_mode(); // addr: 0x0045D380  thinker  pops the mode stack BEFORE the leaving iface on_mode(0)
extern struct ButtonGroup* g_map_mode_btn_group; // addr: 0x007CD12C  observed  world/detail radio-pair group object
extern void ButtonGroup_set_by_id(int id, int a2); // addr: 0x0062B870  observed  thiscall; flips member state by button id
// field: InfoWin +0x58 Font font   ticker font (0x7AD2F8); draws char-by-char into the strip buffer
// field: InfoWin +0x10 RECT panelRect[2]   box-5 panel rects in strip-buffer coords (left, right)
// field: InfoWin +0x80 int curPanel   panel being typed (0/1)
// field: InfoWin +0x94 int altText   hover-toggled alternate string set
// field: InfoWin +0x9C8 int typedChars[2]   per-panel typewriter counters
extern void InfoWin_layout(struct GraphicWin* self);                           // addr: 0x00456300  observed  thiscall; line layout + d7f8 panel box @0x4564A2
extern void InfoWin_paint(struct GraphicWin* self, int panel);                 // addr: 0x00458420  observed  thiscall RET 4; panel -1 = both; types typedChars of each line
extern void InfoWin_box_panel(struct GraphicWin* self);                        // addr: 0x004588B0  observed  thiscall; d7f8 box on panelRect[curPanel]
extern void InfoWin_reset(struct GraphicWin* self, int a2);                    // addr: 0x00458FF0  observed  thiscall RET 4; curPanel=(curPanel-1)&1, d7f8 box (panel clear), layout, paint
extern void InfoWin_tick(struct GraphicWin* self, int a2);                     // addr: 0x00459150  observed  thiscall RET 4; typewriter tick gate
extern struct GraphicWin MessageWin_g;         // addr: 0x007F67F8  thinker   HUD event log (MESSAGES view of the centre console); ListBox part +0x64
extern int  MessageWin_init(/*ecx*/ void* self);                              // addr: 0x00471D50  observed  fastcall; Font_init(hud,12,0) @0x471DA7, rect = MainWin +0xD1C, row stride (B-T)/5, text indent (B-T)/4
extern void MessageWin_add(/*ecx*/ void* self, const char* text, unsigned flags); // addr: 0x00471530  observed  thiscall RET 8; dedups vs last line, appends, caps at 100 rows
extern void MessageWin_draw_icon(void* listwin, int id, int flags, int x, int y, int h); // addr: 0x00471870  observed  cdecl; ListBox item-icon cb (+0x94): sprite at x+4, centred on h
extern int  MessageWin_draw_bg(void* listwin);                                // addr: 0x00471F70  observed  cdecl; ListBox background cb (+0x9C): fill 9 + d7f8 box
extern int  MessageWin_item_color(void* listwin, unsigned flags);             // addr: 0x00471FD0  observed  cdecl; ListBox text-colour cb (+0x98)
extern struct Sprite g_msglog_icon_sprite;     // addr: 0x007F67C8  observed  event-log row arrow (interface.pcx 615,530 16x15), load_box_sprites @0x453AFD
extern int  g_msglog_count;                    // addr: 0x009393D0  observed  event-log row count
// field: MessageWin +0x2C RECT rect   copy of MainWin +0xD1C
// field: MessageWin +0x3C Font font   Arial 12 regular (direct Font_init)
// field: MessageWin +0x94 void* icon_cb   +0x98 color_cb, +0x9C bg_cb
// field: StatusWin +0x15B4 int info_tile_x ; +0x15B8 int info_tile_y   the panel's tile (StatusWin_set_loc); StatusWin_draw_status shows the active unit only while CurVeh stands on it, else that tile's veh_at/base_at
// field: StatusWin +0x15BC int unk_m1 ; +0x15C0 int unk_m1   reset to -1 by StatusWin_set_loc
// field: StatusWin +0x15C4 int unk_m1 ; +0x15C8 int unk_m1 ; +0x15CC int shown_veh ; +0x15D0 int shown_base   written by StatusWin_draw_status before StatusWin_draw_active
// field: StatusWin +0x1530 Font fontS0   private strip font style 0; size (SW==800)?10:12, re-Font_init'd by 10 triples across StatusWin draws
// field: StatusWin +0x1558 Font fontS2   private strip font style 2
// field: StatusWin +0x1580 Font fontS1   private strip font style 1
// field: StatusWin +0x15AC int  fontSizeCache   last size passed to the trio's Font_init (native units)
extern struct FontCache g_label_fontcache;     // addr: 0x0093FB88  observed  3-slot Font cache (fonts +0 x0x28; size keys +0x78; style keys +0x84; LRU order +0x90); unit/map-label text
extern struct Font* FontCache_get(/*ecx*/ struct FontCache* self, int sizeArg, int mulN, int mulD, int style); // addr: 0x005592D0  observed  thiscall RET 0x10; px=(zoomN>0? 50*zoomN/zoomD : (5*sizeArg+80)*10/16)*mulN/mulD, 10->11
extern int  veh_draw();                        // addr: 0x005594F0  thinker   cdecl-frame(buf,veh_id,x,y,size,flags,a7); unit icon+label writer (28 callers: map + StatusWin); font via FontCache_get @0x559DE5 (mul 1/4), text out Buffer_write_cent_l_7 @0x55A11D
extern void MapWin_draw_vehicles(struct Console* self, int x, int y, int px, int py, int a6); // addr: 0x00466CA0  thinker   thiscall RET 0x14; sole map veh_draw site 0x46717E
extern int  g_veh_flag_colors[8];              // addr: 0x0068FA10  observed  by faction; stack-mark mono colour
// field: CChassis +0x4E int8 sprite_flag_x_coord[8]   flag x offset by variant
// field: CChassis +0x56 int8 sprite_flag_y_coord[8]   flag y offset by variant
extern int  pick_top_veh(int veh_id);          // addr: 0x005593E0  thinker   cdecl; stack-top veh for display (veh_draw flags&1)
extern int  veh_fake(int proto_id, int faction_id); // addr: 0x005C1D50  thinker   cdecl; fills scratch veh slot 2048
extern struct Sprite g_flag_sprites[112];      // addr: 0x0078B778  observed  stride 0x2C; unit status flags, 23x30 native
extern int  base_draw();                       // addr: 0x0055AF20  thinker   cdecl-frame(buf,base_id,x,y,size,flags); base-icon writer, same size-sentinel scale as veh_draw; PRACX _cx calls 0x55AF62 (entry+0x42) -- entry hooks OK, never patch NEAR +0x42
extern struct Font* g_maplabel_font;           // addr: 0x0093FC24  observed  Font* last returned by FontCache_get; base_draw pop-box @0x55B3C7 reads +0x10 height metric, set_font sites 0x55B5C1/0x55B633
extern int  Font_init(struct Font* self, const char* name, int size, int style);   // addr: 0x00618F40  observed  thiscall RET 0xC; LOGFONT lfHeight=-size, style bit0 weight 700, bit1 italic, bit2 underline; fills +0xC..+0x1C from GetTextMetrics
// field: Font +0x08 HFONT hfont            CreateFontIndirectA result
// field: Font +0x0C int cell               tmHeight + tmExternalLeading (line pitch)
// field: Font +0x10 int cap_height         tmAscent - tmInternalLeading
// field: Font +0x14 int internal_leading   tmInternalLeading
// field: Font +0x18 int ascent             tmAscent
// field: Font +0x1C int descent            tmDescent
extern int  g_map_zoom_num;                    // addr: 0x00691E6C  observed  map zoom numerator; >0 selects FontCache_get's zoom branch
extern int  g_map_zoom_den;                    // addr: 0x00691E70  observed  map zoom denominator
extern struct Caviar g_vehdraw_caviar;         // addr: 0x008CC828  observed  shared unit-body 3D/flic render object (vehdraw family); zoom float at +0xD5
// field: Caviar +0xA4 uint8_t table_composite   set per Caviar_draw: (flag & 2) == 0 -> the target2 table composite runs (map unit draws: flag 1 | (state&0x2000)>>12)
extern void Caviar_set_zoom(/*ecx*/ struct Caviar* self, float zoom); // addr: 0x006183B0  observed  thiscall; [this+0xD5]=zoom; vehdraw_draw computes zoom = (size+16)*0.07/16 (unarmed) or zoomN*0.07/zoomD (armed)
extern float Caviar_get_zoom(/*ecx*/ struct Caviar* self);            // addr: 0x006183C0  observed  thiscall; reads [this+0xD5] (construct_vehicle chassis multipliers compose on it)
extern void Caviar_reset(/*ecx*/ struct Caviar* self, int keep_z);          // addr: 0x00618470  observed  thiscall RET 4; clears the GLOBAL render target's dirty rect (Buffer_fill 0x9B9108 colour 9, Buffer_fill_2 0x9B96B0); arg 0 also memsets z-plane rows miny..maxy to 0xFFFF UNCLIPPED (stride 512)
extern void* g_caviar_zplane;                  // addr: 0x009B9100  observed  uint16 z-buffer plane, malloc(0x20000) = 256x256x2 @0x618A91, freed @0x618D4A; stride 256 baked (shl 8 / 0x200)
extern struct Buffer g_caviar_target;          // addr: 0x009B9108  observed  Caviar colour render target (256x256 class), filled 9 at reset
extern struct Buffer g_caviar_target2;         // addr: 0x009B96B0  observed  Caviar second render Buffer (mask/aux), Buffer_fill_2 at reset
extern int  g_caviar_dirty_minx;               // addr: 0x009B9690  observed  Caviar dirty rect L (render-target coords); +4 miny 0x9B9694, +8 maxx 0x9B9698, +0xC maxy 0x9B969C
extern int  g_caviar2_dirty_minx;              // addr: 0x009BB438  observed  target2 (0x9B96B0) dirty rect L; +4 T 0x9BB43C, +8 R 0x9BB440, +0xC B 0x9BB444; UnionRect per rasterised object, exclusive R/B, zeroed by Caviar_reset after its fills
extern int  Sprite_draw_4(struct Sprite* self, struct Buffer* dst, int key, int x, int y, int num, int den); // addr: 0x005E9D44  thinker  thiscall; sprite blit core used by the 0x5D8FE0 Buffer_draw variant (NOT by Buffer_draw_2: its software path calls Sprite_draw_2 0x5E4B4A; Buffer_draw_dest_source_2 calls 0x5E811C)
extern void Caviar_draw(/*ecx*/ struct Caviar* self, struct Buffer* dst, int x, int y, int flag); // addr: 0x00617230  observed  thiscall RET 0x10; flag 6 = part icons, 0x17 = preview, |8 = overlay (entry `test cl,1` is [this+4], not flag); renders the constructed model at [this+0xD5] zoom; result bbox via [0x9BB478]+8..+0x14
extern void Caviar_draw_silhouette(/*ecx*/ struct Caviar* self, struct Buffer* dst, int x, int y, int color, int flag); // addr: 0x00617620  observed  thiscall RET 0x14; fills g_caviar_color_table with color, sets obj flag 8, Caviar_draw, clears it
extern void Caviar_draw_flag10(/*ecx*/ struct Caviar* self, struct Buffer* dst, int x, int y, int a5, int flag); // addr: 0x00617670  observed  thiscall RET 0x14; [0x9BB474]=a5, obj flag 0x10 around Caviar_draw
extern void Caviar_rasterize(struct CaviarCtx* ctx, void* draw18, void* a3, int a4); // addr: 0x00639E60  observed  cdecl; point-sampled voxel projection into g_caviar_target; result bbox ctx+8..+0x14; clips to ctx+0x38..+0x4C
extern void Caviar_model_extents(void* draw18, int mode, float* outA, float* outB); // addr: 0x0063A6F0  observed  cdecl; reads model bbox shorts [model+0x14..0x1E], the matrix (+0x20) and translation (+0x14) of the draw block
extern void Buffer_draw_dest_source_2(/*ecx*/ struct Buffer* src, struct Buffer* dst, int key, int x, int y, int num, int den, void* table); // addr: 0x005D8EE0  thinker  thiscall RET 0x1C; colour-table composite (Caviar aux pass @0x6175AC, skipped when draw flag&2)
extern void Caviar_overlay(/*ecx*/ struct Caviar* self, struct Buffer* dst, int x, int y, int bg, void* table, int flag); // addr: 0x006171A0  observed  thiscall RET 0x18; Buffer_fill_2(target,bg), Caviar_draw(flag|8), own Buffer_draw_table(dst,bg,x-128,y-128,1,1,table) @0x6171F8, refill 9, Caviar_reset(flag&1)
extern void Buffer_draw_table(/*ecx*/ struct Buffer* src, struct Buffer* dst, int key, int x, int y, int num, int den, void* table); // addr: 0x005D94B0  observed  thiscall RET 0x1C; keyed blit through a 256x256 table (dst = table[src<<8|dst]); fills sprite desc 0x9B3A50 then Sprite_draw_table_scaled
extern int  Sprite_draw_table_scaled(/*ecx*/ struct Sprite* self, struct Buffer* dst, int key, int x, int y, int num, int den, void* table); // addr: 0x005E8FA5  observed  thiscall RET 0x1C; swaps SCALE_NUM_G/SCALE_DEN_G = num/den around Sprite_draw_table
extern int  Sprite_draw_table(/*ecx*/ struct Sprite* self, struct Buffer* dst, int key, int x, int y, void* table); // addr: 0x005E8FF5  observed  thiscall RET 0x14; table blit core, scaled through SCALE_NUM_G/DEN_G (Sprite_fill_scaling_table, >max reject)
extern int  Sprite_draw_dest(/*ecx*/ struct Sprite* self, struct Buffer* dst, int key, int x, int y, void* table); // addr: 0x005E5833  thinker  thiscall RET 0x14; capped scaled core, Sprite at [ebp-0x5C]
extern int  Sprite_draw_dest_unk1(/*ecx*/ struct Sprite* self, struct Buffer* dst, int x, int y, void* table); // addr: 0x005E66A2  thinker  thiscall RET 0x10; capped scaled core, no key arg
extern int  Sprite_draw_dest_source(/*ecx*/ struct Sprite* self, struct Buffer* dst, int key, int x, int y, void* table); // addr: 0x005E741C  thinker  thiscall RET 0x14; capped scaled core
extern int  Sprite_draw_dest_unk2_2(/*ecx*/ struct Sprite* self, struct Buffer* dst, int key, int x, int y, void* table); // addr: 0x005E81BC  thinker  thiscall RET 0x14; capped scaled core (Buffer_draw_dest_source_2's)
extern unsigned char g_caviar_overlay_table[0x10000]; // addr: 0x006EEF7C  observed  Probability Sheath translucency table (DesignWin 0x4355AC/0x43635B, PartPicker 0x4332F1 Caviar_overlay calls, bg 0x18)
extern int  g_caviar_raster_busy;           // addr: 0x009BE6C4  observed  re-entrancy guard of Caviar_rasterize (set -> a nested call spins forever)
extern float g_caviar_lod_threshold;        // addr: 0x00671010  observed  Caviar_rasterize: zoom*partScale <= this -> low-zoom part mode flag into 0x63E950
extern void Caviar_rasterize_part(struct CaviarCtx* ctx, void* part, float* pos, float* mat, void* clip, void* a6, float scale, int lowzoom); // addr: 0x0063E950  observed  cdecl; per-part voxel projection
extern void Caviar_ctx_select_plotters(struct CaviarCtx* ctx); // addr: 0x0063AD60  observed  cdecl; picks the plotter pair by target desc+0x20 (1=8-bit) and ctx flag&1 into ctx+0x6C/+0x70
extern void Caviar_plot8_full(int x, int y, int z, int nruns, void* runs, int mode); // addr: 0x006647F0  observed  cdecl asm; 8-bit voxel plotter, no clip; mode bit0 = 1px footprint, else 2x2; bit4 = flag&4 part; bit5 = flag&8 part
extern void Caviar_plot8_clip(int x, int y, int z, int* clip, int nruns, void* runs, int mode); // addr: 0x00664000  observed  cdecl asm; 8-bit voxel plotter, clipped twin of Caviar_plot8_full
extern void Caviar_plot8_full_alt(int x, int y, int z, int nruns, void* runs, int mode); // addr: 0x00665640  observed  cdecl asm; 8-bit plotter pair chosen by Caviar_ctx_select_plotters when ctx flag&1 (setup 0x63AF40)
extern void Caviar_plot8_clip_alt(int x, int y, int z, int* clip, int nruns, void* runs, int mode); // addr: 0x00664E50  observed  cdecl asm; clipped twin of Caviar_plot8_full_alt
extern void Caviar_plot16_full(void);            // addr: 0x00666440  observed  cdecl asm; 16-bit target plotter (desc+0x20 == 2), setup 0x63AEE0; clipped twin 0x665CA0
extern void Caviar_plot16_full_alt(void);        // addr: 0x00667B20  observed  cdecl asm; 16-bit plotter when ctx flag&1, setup 0x63AF20; clipped twin 0x667380
extern void Caviar_plot8_bind_target(void);   // addr: 0x00664D51  observed  writes the target data/z base + pitch into the plotters' self-modifying address slots (2x2 block = D,D+1,D+pitch,D+pitch+1)
extern void Caviar_plot8_setup(void);         // addr: 0x0063AF00  observed  ctx+0x7C for the 8-bit pair: bind_target + 0x6646FB + 0x666F68, jmp 0x66731C
extern void Caviar_cube_axes(void);           // addr: 0x006404F0  observed  builds the run-direction step tables 0x9C0840.. (8.8 fixed) from the axis vectors 0x9C0A4C/50/54
extern int  g_caviar_face_mask;               // addr: 0x009C0B74  observed  1<<dir: voxel runs are drawn only when [run]&mask (view-facing)
extern void* g_caviar_z_base;                 // addr: 0x009BE6A4  observed  bound target z-plane base (u16 per px)
extern void* g_caviar_data_base;              // addr: 0x009BE6A8  observed  bound target colour base (u8 per px)
extern int  g_caviar_data_pitch;              // addr: 0x009BE6B0  observed  bound target colour pitch (bytes)
extern int  g_caviar_z_pitch;                 // addr: 0x009BE6B4  observed  bound target z pitch (bytes)
extern unsigned char g_caviar_desc_flag;      // addr: 0x009BB468  observed  target descriptor +0x20: 1 = 8-bit target (set at init 0x618C05)
extern void Caviar_part_light_setup(void* mtx, void* a2, float scale, void* a4); // addr: 0x0063FCA0  observed  cdecl; rotates the light into part space (0x9C0A64), quantizes elevation to 24 tables x azimuth 89 bins, sets g_caviar_shade_table
extern void Caviar_part_matrix_fixed(float* mtx9); // addr: 0x0063FA80  observed  cdecl; part matrix x256 -> 8.8 ints 0x9C0A40..4A (x,y rows, shorts) + 0x9C0A4C/50/54 (depth row, ints)
extern unsigned char* g_caviar_shade_tables[24]; // addr: 0x006A5A00  observed  per light-elevation bin: 2144-byte table, normal code (23 elev x 89 az = 11 bits) -> shade 0..23; light azimuth folds in as byte offset (0x59 - az)
extern unsigned char* g_caviar_shade_table;   // addr: 0x009BE6A0  observed  current part's shade table (esp inside the plotters)
extern short g_caviar_part_mtx_fixed[6];      // addr: 0x009C0A40  observed  8.8 projected voxel axis steps: x row +0/+2/+4, y row +6/+8/+0xA
extern float g_caviar_light_part[3];          // addr: 0x009C0A64  observed  light direction in part space
extern float g_caviar_zoom;                   // addr: 0x009C0B00  observed  current draw zoom (object zoom x view)
extern struct CaviarCtx* g_caviar_ctx;      // addr: 0x009BB478  observed  rasterizer context ptr (+8..+0x14 last result bbox L,T,R,B inclusive; +0x38..+0x4C clip rect in target space L,T,R,B,W,H; +0x54 colour table)
extern struct Caviar* g_caviar_current;     // addr: 0x009BB470  observed  the Caviar object being rasterized (set around Caviar_rasterize)
extern int  g_caviar_aux_rect;              // addr: 0x009BB438  observed  aux-pass dirty rect (4 ints), zeroed by Caviar_reset(0)
extern int  g_caviar_last_bbox;             // addr: 0x009B96A0  observed  copy of the ctx result bbox (4 ints) via 0x618520
extern char g_caviar_color_table[0x1800];   // addr: 0x009B9C38  observed  silhouette colour table (memset to the colour by Caviar_draw_silhouette)
// field: Caviar +0x4 uint32 flags          bit0 enabled, bit3 silhouette table, bit4 flag10, bit5 render x2 + composite 1/2
// field: Caviar +0x14 struct Buffer* dst     draw block starts here (+0x18 passed to the rasterizer)
// field: Caviar +0x1C void* model             constructed model ptr (0 = nothing to draw)
// field: Caviar +0x2C float translation[3]    draw centring accumulator (flag&4 path: -= model centre)
// field: Caviar +0x38 float matrix[9]         rotation matrix (flag&0x10 resets to identity for the draw)
// field: Caviar +0xA4 uint8 composite         0 when draw flag&2 (aux composite skipped)
// field: Caviar +0xED int clip[6]             render clip window (0,0,0xFF,0xFF,0x100,0x100)
// field: Caviar +0x13CC void* model_ready     non-zero once a model is constructed (checked at Caviar_draw entry)
extern float g_flic_zoom_base;                 // addr: 0x0066DF18  observed  const 0.07f — vehdraw unit-body zoom coefficient
extern float g_flic_zoom_recip16;              // addr: 0x0066D8D0  observed  const 0.0625f (1/16) — composes with 0.07f in vehdraw_draw's unarmed branch
// field: Caviar +0xD5 float zoom   render zoom (Caviar_set_zoom/get_zoom)
// field: StatusWin +0x30 Caviar caviar   StatusWin's own flic object (init zoom 0.18 @0x4BA0DB)
extern const char** g_hud_font_name;           // addr: 0x00691B2C  observed  font-name string ptr used by StatusWin trio + FontCache Font_init
extern const char** g_hud_font_name_narrow;    // addr: 0x00691B30  observed  "Arial Narrow" string ptr; config_popups pool face for sizes > 12 (else g_hud_font_name)
extern int  g_hud_box6_rect[4];                // addr: 0x007AF50C  observed  HUD unit-row (box6) strip device rect {L,T,R,B}; T/R/B reads confirmed @0x4B80A4/0x4B8167
extern struct NetMessage* NetMsg_g;            // addr: 0x00805338  thinker   notification/chat ticker popup above the HUD (NetMessage : Popup)
extern struct NetMessage g_netmsg_2;          // addr: 0x007FFF80  observed  second NetMessage instance
extern int  NetMsg_pop(struct NetMessage* self, const char* label, int delay_ms, int a4, const char* filename); // addr: 0x0047A890  thinker  thiscall
extern int  NetMsg_pop_2(const char* label, const char* filename); // addr: 0x0050B9E0  thinker
extern void NetMsg_ctor();                     // addr: 0x0047ACF0  thinker  thiscall
// field: NetMessage +0x537C int loc_x   NetMsg_ctor arg; BasePop_set_loc x at show (0x47A94F)
// field: NetMessage +0x5380 int loc_y   NetMsg_ctor arg; BasePop_set_loc y at show
extern void NetMsg_close();                    // addr: 0x0047A7D0  thinker  thiscall
extern void NetMsg_timer_daemon();             // addr: 0x0047A800  thinker
extern struct CTimeControl* TimeControl_table; // addr: 0x0094F1B8  thinker   6 entries, 32B each; [0].name = "No Time Control" label
extern struct GraphicWin* MainWin_g;           // addr: 0x007AE820  thinker   MainWindow instance = the HUD strip window (1024x257 bottom-centered; 800x257 at 800x600)
extern int MainWin_build(struct GraphicWin* self); // addr: 0x00459680  observed  fastcall(ecx); builds the WHOLE HUD strip: seed rect table +0xA1C..+0xDFC, console pcx loads + 31 sprite extracts, 3 Font_init, 12 BaseButton_init, GraphicWin_init @0x459F28
extern int g_console_strip_height;             // addr: 0x007AF59C  observed  = MainWin+0xD7C; runtime HUD strip height (213; single write = literal 0xD5 in MainWin_build); read by Popup_show/BaseWin_init/FileDlg_layout/Console_init
// field: MainWin +0xA1C RECT rcStrip   strip window rect L,T,R,B = (SW-1024)/2, SH-257, +1024, SH (0,343,800,600 at 800x600)
// field: MainWin +0xD7C int  stripHeight   213 (=g_console_strip_height global)
// field: MainWin +0xD84 RECT rcPanelSeeds   start of the native-literal seed rects all strip widgets derive from (through +0xDFC)
// field: MainWin +0x51C8 struct FlatButton btnLocatorGlobe   base-locator globe toggle (HUD group #10; 24x24 icon at 1:1 on a bevel face, pressed face dithers E0/E2)
// field: MainWin +0x5D14 struct FlatButton btnLocatorGrid    base-locator grid toggle (HUD group #10)
extern int Font_init(struct Font* self, const char* fontName, int height, int style); // addr: 0x00618F40  thinker  thiscall
// field: MainWin +0x2166C Font fontA14   strip font Arial 14 style 1 (Font_init @0x459E34) = g_popup_title_font
// field: MainWin +0x21694 Font fontA12   strip font Arial 12 style 0 (Font_init @0x459E49)
// field: MainWin +0x216BC Font fontA12b  strip font Arial 12 style 1 (Font_init @0x459E5F)
// field: MainWin +0x1530 Font fontLabel7   box-6 cell label font h=7 (=0x7AFD50; set on strip buf @0x4B8534; label y uses its +0x1C height @0x4B86DD)
// field: MainWin +0xA5C RECT rcMenuBtn     MENU seed rect (11,20,117,34)
// field: MainWin +0xA6C RECT rcCommlinkBtn COMMLINK seed rect (908,22,1014,36)
// field: MainWin +0xA7C RECT rcTurnBand    TURN COMPLETE band rect (783,61,1016,84); computed @0x459CEC from +0xD90 seed; feeds Flic_init x,y @0x45A009
// field: MainWin +0xA8C RECT rcWorldMapBtn  box-10 btn 0x3EE rect (904,214,958,246); computed @0x459DC0 from +0xD90 (mirror of +0xA9C, 2px gap)
// field: MainWin +0xA9C RECT rcDetailMapBtn box-10 btn 0x3EF rect (960,214,1014,246); computed @0x459D7F: (D90.R-6-54, D90.B-6-32)
// field: MainWin +0xD80 RECT rcConsoleLeft   left console seed (alias 0x7AF5A0)
// field: MainWin +0xD90 RECT rcConsoleRight  right console seed (779,56,1020,252), written @0x4598FF (1024 branch; 800 twin @0x45976F); alias 0x7AF5B0
// field: MainWin +0xCFC RECT rcMinimap      WorldWin minimap window rect (780,88,1019,207)
// field: MainWin +0xD0C RECT rcMissionBox   box-9 mission-year text box (785,214,901,246)
// field: MainWin +0xDA0 RECT rcConsoleCenter center console seed (262,66,763,172), written @0x459912; alias 0x7AF5C0
// field: MainWin +0x24550 Flic turnFlc     turn.flc object (=0x7D2D70; Flic_init @0x45A009)
// field: MainWin +0xAAC RECT rcArrowBtn8   buttons[8] id 0x3F0 seed rect (init @0x45AE30 region)
// field: MainWin +0xABC RECT rcArrowLeft   buttons[9] id 0x3F1 seed rect; unit-row left scroll arrow
// field: MainWin +0xACC RECT rcArrowRight  buttons[10] id 0x3F2 seed rect; unit-row right scroll arrow
// field: MainWin +0xE00 FlatButton buttons0   =0x7AF620 id 0x3E8 (HUD M); buttons[] array start, stride 0xB4C; 20x20, seed rect +0xA2C (734,75,754,95 at 1024); canvas +0x444=0x7AFA64
// field: MainWin +0x194C FlatButton buttons1  =0x7B016C id 0x3E9 (HUD I); 20x20, seed rect +0xA3C (734,143,754,163 at 1024); canvas +0x444=0x7B05B0
// field: MainWin +0x2498 FlatButton buttons2  =0x7B0CB8 id 0x3EA; 20x38, seed rect +0xA4C (734,100,754,138 at 1024); canvas +0x444=0x7B10FC; sprites +0xAC8=0x78D960/88/B0
// field: MainWin +0xA2C RECT rcBtn0Seed   buttons[0] id 0x3E8 (M) seed, top-right of center console (from +0xDA0)
// field: MainWin +0xA3C RECT rcBtn1Seed   buttons[1] id 0x3E9 (I) seed, bottom-right of center console
// field: MainWin +0xA4C RECT rcBtn2Seed   buttons[2] id 0x3EA seed, between the two
// field: MainWin +0x22E28 Sprite arrowSet1[3]  =0x7D1648 left-arrow art 12x42, 3 states (extract loop @0x459xxx y=0x99); used by buttons8 AND buttons9
// field: MainWin +0x22EAC Sprite arrowSet2[3]  =0x7D16CC right-arrow art 12x42, 3 states (y=0xC4); used by buttons10
// field: MainWin +0x6860 FlatButton buttons8   =0x7B5080 id 0x3F0; state sprites +0x22E28/54/80
// field: MainWin +0x73AC FlatButton buttons9   =0x7B5BCC id 0x3F1 unit-row LEFT arrow (12x42 art); shown by BaseWin_draw_garrison overflow + StatusWin_draw_status
// field: MainWin +0x7EF8 FlatButton buttons10  =0x7B6718 id 0x3F2 unit-row RIGHT arrow; state sprites +0x22EAC/D8/22F04
extern int  painter_editor_info(void* self);                                   // addr: 0x0045B550  observed  strip painter (map name/size), gated g_console_mode_id==0x3EA && ScreenWidth>=1024
extern int  MainWin_tile_panels(void* self);                                   // addr: 0x0045C290  observed  thiscall RET 4; console-art restore: 4 seed rects (D80; DD0|DB0 + DC0|DA0 by g_console_big_center; D90), each inset 1, via Buffer_tile_phase(tex=[0x78D6B0], x, y, x, y, w-2, h-2); 12 E8 callers, no table refs
extern void Buffer_tile_phase(struct Buffer* self, struct Buffer* tex, int phaseX, int phaseY, int x, int y, int w, int h); // addr: 0x005DA860  observed  thiscall RET 0x1C; repeating-tile fill, absolute-position phase (idiv by tex w/h); clips to rect via its own set_clip pair @0x5DA8F9/0x5DA9E0
extern int  Buffer_write_raw_l(struct Buffer* self, char* str, int x, int y, int len); // addr: 0x005DBD00  thinker  thiscall RET 0x10; calls [this+0x8] pfcnScrollText(str,x,y,n) if nonzero
extern struct Buffer* g_console_tile_texture;                                  // addr: 0x0078D6B0  observed  -> static Buffer 0x75F3E0 (24x24 flat backdrop tile; NOT the pcx ledge art)
extern void MainWin_draw_box9(struct GraphicWin* self);                        // addr: 0x0045BE80  observed  thiscall; HUD box-9 painter (mission-year box + map-button frame)
extern int  MainWin_draw_center_mode(struct GraphicWin* self);                 // addr: 0x0045BC50  observed  thiscall (virtual, vtbl slot .rdata 0x66C5C8); center-console mode painter; 0x3EA arm = editor frames (Buffer_box_sprite @0x45BCCF/+0xD4C, @0x45BCEE/+0xD5C) + buttons + info
extern int  MainWin_item_back(struct GraphicWin* self, struct GraphicWin* win, int a2, int state, RECT* rect); // addr: 0x0045C8F0  observed  thiscall RET 0x10; MainWin vtbl+0x2C: forwards to the current mode's iface +0x48
extern int  g_console_mode_id;                                                 // addr: 0x007CD11C  observed  = MainWin+0x1E8FC centre-panel mode; 0x3EA = scenario-editor palette panel (not an iface mode)
extern int32_t g_editor_edit_mode;             // addr: 0x00945AE0  observed  "Editing:" mode index 0..0x1D
extern int32_t g_editor_brush_size;            // addr: 0x00945AE4  observed  brush-size index 0..5
extern void Console_editor_paints(int a1, int a2); // addr: 0x004E0A50  thinker  editor paint dispatch (palette button click)
extern void Console_editor_set_brush(int a1);  // addr: 0x004E0EA0  thinker  brush-size setter
extern char* MapFilePath;                      // addr: 0x0094A2BC  thinker  current map file path string
extern int32_t MapAreaX;                       // addr: 0x00949870  thinker  map width
extern int32_t MapAreaY;                       // addr: 0x00949874  thinker  map height
extern int32_t MapToggleFlat;                  // addr: 0x0094988C  thinker  flat/round flag
extern int32_t MapCloudCover;                  // addr: 0x0094A2B4  thinker  rainfall index
// field: MainWin +0xADC RECT paletteSeeds[25]   tile-palette seed rects; derived @0x45AF62-0x45B020 from rcConsoleCenter+7 + native cell 43x18, column-major 5 rows, pitch cell+1
// field: MainWin +0xC6C RECT brushSeeds[6]      red brush-button seeds; @0x45B022-0x45B0EB x0=paletteSeeds[24].right+9, 3 rows x 2 cols 24x24 pitch h+1; skipped at SW==800 (je @0x45B30B)
// field: MainWin +0xD4C RECT paletteUnion       palette frame rect (seeds union +-3)
// field: MainWin +0xD5C RECT brushUnion         red-button frame rect (union +-3)
// field: MainWin +0xD6C RECT editorInfoRect     info-text rect @0x45B446-0x45B49A: left=brushUnion.right+3, right=[+0xA3C].left-3
// field: MainWin +0x8A44 FlatButton paletteButtons[25]  =0x7B7264 ids 0x3F3..0x40B stride 0xB4C; BaseButton_init @0x45B154; group +0x1E9A0
// field: MainWin +0x1A4B0 FlatButton brushButtons[6]    =0x7C8CD0 ids 0x40C..0x411; BaseButton_init @0x45B373; group +0x1EA34
// field: MainWin +0x21E00 Sprite paletteSprites[75]  43x18 x3 states, interface.pcx sheet (350,245) extract loop @0x45A6FD-0x45A78C; dims read back @+0x21E18/+0x21E1C
// field: MainWin +0x22AE4 Sprite brushSprites[18]    24x24 x3 states, sheet (465,438) loop @0x45A78E-0x45A801
// field: MainWin +0x1E8FC int center_mode_id         = g_console_mode_id 0x7CD11C

// ============================================================================
// Spot (menu hit-test rects; __thiscall, callee cleanup)
// ============================================================================
extern void Spot_init(void* self, int count);                                  // addr: 0x005FA8A0  thinker  thiscall
extern void Spot_shutdown(void* self);                                         // addr: 0x005FA830  thinker  thiscall
extern void Spot_add(void* self, int idx, int flag, int X, int Y, int W, int H); // addr: 0x005FA960  thinker  thiscall
extern void Spot_get_rect(void* self, int idx, int zero, RECT* out);           // addr: 0x005FAC00  thinker  thiscall

// ============================================================================
// Buffer drawing / blit / text primitives (thiscall; RET imm where noted)
// ============================================================================
extern struct Palette g_main_palette;                                          // addr: 0x0094C590  observed  PALETTEENTRY colors[256] at +0 (r,g,b,flags); pairs GDI HPALETTE 0x9B8178; NOT guaranteed the live screen palette in every context (thunk_chev_coverage nearest-search source; thunk_portrait_avg reads dest Buffer+0xA4 instead)
extern struct Palette* g_active_palette;                                       // addr: 0x009B8180  observed  Palette* that Buffer_load_pcx calls receive and Win_flip_rect syncs g_screen_buffer to before the BitBlt
extern int  Buffer_ctor(struct Buffer* self);                                  // addr: 0x005D7210  thinker  constructs 0x588-byte Buffer (pixels via Buffer_resize)
extern int  Buffer_resize(struct Buffer* self, int w, int h);                  // addr: 0x005D79C0  thinker  RET 0x08
extern void Buffer_dtor(struct Buffer* self);                                  // addr: 0x005D7410  thinker  thiscall; near ret; destroys a Buffer_ctor'd buffer
extern int  Buffer_get_data(struct Buffer* self);                              // addr: 0x005E3373  observed  thiscall; acquire/lock pixel data
extern void Buffer_free_data(int a1);                                          // addr: 0x005E34A3  observed  release pixel-data lock
extern void Buffer_set_clip(struct Buffer* self, RECT* rect);                  // addr: 0x005D8000  thinker  RET 0x04; copies rect, clip[+0x20] = IntersectRect(bounds[+0x30], rect) — no intersect with prior clip; draw primitives cull HALF-OPEN (y==clip.B / x==clip.R culled, B-1/R-1 draw)
extern void Buffer_set_font(struct Buffer* self, struct Font* f0, struct Font* f1, struct Font* f2, struct Font* f3); // addr: 0x005DAC70  thinker  thiscall RET 0x10; f0->+0x52C only if f0->+8 HFONT != 0; f1/f2/f3 -> +0x530/+0x534/+0x538 unconditionally
extern int  Buffer_write_raw_l(struct Buffer* self, const char* str, int x, int y, int len); // addr: 0x005DBD00  thinker  thiscall; SelectObject slot HFONT, TextOutA at (x, y + font[+0x10]) on the TA_BASELINE DC; returns x + width
extern int  Buffer_load_pcx(struct Buffer* self, char* name, void* pal, int a4, int a5); // addr: 0x005D7DE0  thinker  thiscall RET 0x10; RESIZES self to the pcx dims
extern int  GraphicWin_load_pcx(struct GraphicWin* self, char* name, void* pal, int a4, int a5); // addr: 0x005D5500  observed  thiscall RET 0x10; skip if [+0x98]&0x800000 else Buffer_load_pcx(self+0x444)
extern void Buffer_change_color_3(struct Buffer* self, int a2, int y, int w, int h, int a6, int shade); // addr: 0x005E2070  observed  thiscall RET 0x18; darkening band (credits fade strips)
extern void Buffer_set_text_color(struct Buffer* self, int color, int a3, int a4, int a5); // addr: 0x005DACB0  thinker  thiscall RET 0x10; a3..a5 -> +0x54C shadow_color, +0x55C/+0x56C shadow_dx/dy
extern int  Buffer_get_pixel(struct Buffer* self, int x, int y);               // addr: 0x005E2210  thinker  thiscall
extern void Buffer_box_sprite(struct Buffer* self, RECT* rect, void* sprite_set); // addr: 0x005E2DD3  observed  9-slice box: corners FUN_005e4b4a(.,.,1,1) native + edges Buffer_tile_2 native cross-thickness; rect HALF-OPEN (R stroke col R-1)
extern struct BoxSpriteParams DAT_0078d690;                                    // addr: 0x0078D690  observed  popup window backdrop (filled) 9-slice
extern struct BoxSpriteParams DAT_0078d5a0;                                    // addr: 0x0078D5A0  observed  hollow frame 9-slice; used for title-outer AND the outer-union frame
extern struct BoxSpriteParams DAT_0078d618;                                    // addr: 0x0078D618  observed  title inner-border 9-slice
extern struct BoxSpriteParams DAT_006846b0;                                    // addr: 0x006846B0  observed  ornate popup frame 9-slice; TL corner canvas 61x44
extern struct BoxSpriteParams DAT_0078d528;                                    // addr: 0x0078D528  observed  hollow frame around the whole option-button block (Popup_on_draw_background @0x406154)
extern struct BoxSpriteParams DAT_0078d550;                                    // addr: 0x0078D550  observed  d528 family state 1 (HOVER) cell frame; instance = d528 + state*0x28
extern struct BoxSpriteParams DAT_0078d578;                                    // addr: 0x0078D578  observed  d528 family state 2 (SELECTED) cell frame; fill pair 0xBF/0x53
extern struct BoxSpriteParams DAT_0078d960;                                    // addr: 0x0078D960  observed  per-OPTION row frame base; instance = d960 + idx*0x28 (normal/hover/selected states)
extern struct BoxSpriteParams DAT_0078d988;                                    // addr: 0x0078D988  observed  d960 family state 1: the only set with a stroke, 1-px E0 ring
extern struct BoxSpriteParams DAT_0078d9b0;                                    // addr: 0x0078D9B0  observed  d960 family state 2: E1 / E0 fill, no stroke
extern int  Buffer_box(struct Buffer* self, int x0, int y0, int x1, int y1, int color_h, int color_v); // addr: 0x005E3193  observed  thiscall; coordinate-arg twin of Buffer_box_2 (same 1px outline); OptionList selection-ring caller @0x610FE3
extern int  Buffer_box_2(struct Buffer* self, RECT* rect, int color_h, int color_v); // addr: 0x005E3203  thinker  1px box OUTLINE of the HALF-OPEN rect [L,R)x[T,B): top row T cols L+1..R-1 / bottom row B-1 cols L..R-2 (color_v) / left col L rows T..B-2 (color_h) / right col R-1 rows T+1..B-1; 2x2 rect draws NOTHING (zero-span); box6 cell-highlight caller @0x4B8764
extern void Sprite_draw_2(struct Sprite* self, struct Buffer* dest, int key, int x, int y, int scaleNum, int scaleDen); // addr: 0x005E4B4A  observed  thiscall (self=ecx); top-left (x,y), size *num/den (NN); 1,1 = native
extern int  Buffer_draw_2(struct Buffer* src, void* dest, int keyColor, int X, int Y, int scaleNum, int scaleDen); // addr: 0x005D84C0  thinker  RET 0x18; keyed UNIFORM-scale blit
extern int  Sprite_blit_scaled_core(struct Buffer* src, void* dest, unsigned int key, int x, int y); // addr: 0x005E4B9A  observed  thiscall; keyed NN scaled-blit core (Sprite_draw_2 wraps it, setting scale globals 0x696D18/0x696D1C); dispatches 1:1 / shrink(num<den) / expand(num>den)
extern void Sprite_fill_scaling_table(void);                                   // addr: 0x005EB20F  observed  rebuilds NN scale-ratio tables when num/den changes
extern int* Sprite_get_clipped_x_table_expand(RECT* full, RECT* clip, short* outDx, short* outSx, int* a5, int* outRun); // addr: 0x005EAB0F  observed  per-src-column dest-run table (num>den)
extern unsigned char* Sprite_get_clipped_y_table_expand(RECT* full, RECT* clip, short* outDy, short* outSy, int* a5, int* outRows); // addr: 0x005EABBF  observed  per-src-row dest-row repeat table (num>den)
extern int* Sprite_get_clipped_x_table_shrink(RECT* full, RECT* clip, short* outSx, short* outDx, int* a5, int* outRun); // addr: 0x005EAC6F  observed  per-src-column dest-run table (num<den)
extern unsigned char* Sprite_get_clipped_y_table_shrink(RECT* full, RECT* clip, short* outSy, short* outDy, int* a5, int* outRows); // addr: 0x005EACFF  observed  per-src-row dest-row table (num<den)
extern int  Buffer_copy_3(struct Buffer* src, void* dst, int srcX, int srcY, int srcW, int srcH, int dstX, int dstY, int dstW, int dstH); // addr: 0x005D9610  thinker  RET 0x24; stretch blit = GDI StretchBlt(SRCCOPY), clips to dest (bounds-safe), non-averaging palette scale keeps key index; ret 7/0x10 BEFORE StretchBlt on HDC acquisition failure (calls the +0x58 sub-object restore hook, never retries; src hdc refcount +0x68 leaks +1 per call)
extern int  Buffer_copy_4(struct Buffer* src, void* dst, int srcX, int srcY, int dstX, int dstY, int srcW, int srcH); // addr: 0x005DFF00  thinker  RET 0x1C; 1:1 blit
extern int  Buffer_tile(struct Buffer* self, void* sprite, int srcOffX, int srcOffY, int destX, int destY, int destW, int destH); // addr: 0x005DA860  observed  thiscall RET 0x1C; tiles sprite at NATIVE size (Buffer_copy_4 1:1, step=spriteW/H) to fill dest rect
extern int  Buffer_tile_mask(struct Buffer* self, void* fill, int x, int y, int phaseX, int phaseY, int w, int h, int mask); // addr: 0x005DA6C0  observed  thiscall RET 0x20; 1:1 tile of fill over rect replacing mask-colored pixels only (Buffer_box_sprite masks the fill over every border piece; pos==phase at all callers)
extern int  Buffer_tile_2(struct Buffer* self, void* src, int a3, int a4, int x, int y, int W, int H); // addr: 0x005DA9F0  thinker  tiles a sprite into a dest rect
extern void GraphicWin_fill_2(struct GraphicWin* self, struct RECT* rect, int color); // addr: 0x005D5350  observed  thiscall RET 8; solid fill of a window-local rect
extern void Buffer_line_2(struct Buffer* self, int x1, int y1, int x2, int y2, int color); // addr: 0x005E15F0  thinker  thiscall RET 0x14; 1px Bresenham (x-major when |dx|>=|dy|), clipped; x1==x2 -> vline_2, y1==y2 -> hline_2
extern void Buffer_line(struct Buffer* self, int x1, int y1, int x2, int y2, int colour2, int colour, int len2, int len, int phase); // addr: 0x005E09D0  thinker  thiscall RET 0x24; dashed: colour2 runs len2 px, colour runs len px, phase mod (len2+len); colour2 -1 skips; clipped to the Buffer clip
extern void Buffer_hline_2(struct Buffer* self, int x0, int x1, int y, int color); // addr: 0x005E1A80  observed  thiscall RET 0x10; horizontal run [x0,x1] inclusive; NO-OP when x0==x1 (cmp/je @0x5e1ac4) -> can't plot a single pixel
extern void Buffer_vline_2(struct Buffer* self, int x, int y0, int y1, int color); // addr: 0x005E1BF0  observed  thiscall RET 0x10; vertical run [y0,y1]; NO-OP on zero-length span (same guard as Buffer_hline_2)
extern void Buffer_put_pixel(struct Buffer* self, int x, int y, int color);    // addr: 0x005E2330  observed  thiscall RET 0x0C; single pixel (use this, not a zero-length hline/vline)
extern void Buffer_fill(struct Buffer* self, int x, int y, int w, int h, int color); // addr: 0x005D8240  thinker  thiscall RET 0x14; SetRect(x,y,x+w,y+h) -> Buffer_fill_3; FLC black-frame chunk handler calls it @0x62AE39
extern void Buffer_fill_3(struct Buffer* self, RECT* rect, int color);         // addr: 0x005DFCD0  observed  thiscall RET 0x08; solid rect fill (respects clip [+0x20])
extern void Buffer_write_cent_l_7(struct Buffer* self, const char* str, RECT* rect, int len); // addr: 0x005DD130  thinker  RET 0x0C; centered text in rect
extern void Buffer_write_cent_l_5(struct Buffer* self, const char* str, int x, int y, int w, int len); // addr: 0x005DD020  thinker  centered text at (x,y) in width w; box-6 cell label writer @0x4B8715; -> wmfr_l
extern int  Buffer_init(struct Buffer* self, int w, int h, int flags, void* surf); // addr: 0x005D7670  observed  thiscall; same-dims early-out ret 0; W->+0x80, -H->+0x84 (= embedded BITMAPINFO @+0x7C), CreateCompatibleDC->+0x64 + CreateDIBSection->+0x78/bits +0x54, stride (w+3)&~3 ->+0x4A8; GDI-mode fail ret 1/3 silent
extern int  point_in_rect(int x, int y, RECT* r);                              // addr: 0x005FA7E0  observed  cdecl; 1 = inside
extern void Buffer_wrap_cent_4(struct Buffer* self, const char* str, int x, int y, int width); // addr: 0x005DD920  thinker  wrapped+centered text at (x,y) in width; FlatButton label writer @0x608441; -> write_cent_l_5
extern void Buffer_write_l(struct Buffer* self, struct Font* f, const char* str, int x, int y, int len); // addr: 0x005DB580  thinker  explicit-Font left text; -> wmfr_l
extern void Buffer_write_cent_l_2(struct Buffer* self, struct Font* f, const char* str, RECT* rect, int len); // addr: 0x005DB720  thinker  explicit-Font centered; -> write_cent_l_7
extern void Buffer_wrap_cent_3(struct Buffer* self, struct Font* f, const char* str, RECT* rect); // addr: 0x005DBC00  thinker  explicit-Font wrapped+centered; -> wrap_cent_6
extern void Buffer_write_l_3(struct Buffer* self, const char* str, int x, int y, int len); // addr: 0x005DCEA0  thinker  left text at (x,y); -> wmfr_l
extern void Buffer_write_l_4(struct Buffer* self, const char* str, RECT* rect, int len); // addr: 0x005DCF40  thinker  left text in rect; -> wmfr_l at y = top + (bottom - top - Font.cap_h)/2
extern void Buffer_write_cent_l_8(struct Buffer* self, const char* str, int x, int y, int len); // addr: 0x005DD250  thinker  centered at (x,y); -> wmfr_l
extern void Buffer_write_right_l_4(struct Buffer* self, const char* str, int x, int y, int a5, int len); // addr: 0x005DD300  thinker  right-aligned; -> wmfr_l
extern void Buffer_set_text_color3(struct Buffer* self, int a2, int a3, int a4, int a5); // addr: 0x005DAD10  thinker  thiscall RET 0x10; set text colour
extern void Buffer_write_right_l_5(struct Buffer* self, const char* str, int x, int y, int len); // addr: 0x005DD3B0  thinker  right-aligned at (x,y); -> wmfr_l
extern void Buffer_write_right_l_6(struct Buffer* self, const char* str, RECT* rect, int len); // addr: 0x005DD450  thinker  right-aligned in rect; -> wmfr_l
extern int  Buffer_wrap_3(struct Buffer* self, const char* str, int x, int y, int w); // addr: 0x005DD730  thinker  thiscall; wrapped left text at (x,y) width w, returns next y; -> wmfr_l x2
extern int  Buffer_wrap_cent_6(struct Buffer* self, char* str, int* rect);     // addr: 0x005DDAB0  thinker  wrapped+centered in rect; -> write_cent_l_5
extern void Buffer_set_clip_2(struct Buffer* self, RECT* rect);                // addr: 0x005D8200  thinker  RET 0x04; clip variant
extern void Buffer_fill_2(struct Buffer* self, int color);                     // addr: 0x005DFB50  observed  thiscall RET 4; fills the WHOLE buffer with color (GraphicWin_clear's opaque arm)
extern void Sprite_draw_mono_2(struct Sprite* self, struct Buffer* dest, int key, int x, int y, int color); // addr: 0x005E3E50  thinker  thiscall RET 0x14; monochrome keyed sprite draw, scale from SCALE_NUM_G/DEN
extern int  Buffer_write_strings(int* strings, int x, int y, int width, int a5); // addr: 0x005DB040  observed  popup BODY text list writer; per-line -> Buffer_write_multi_font_raw_l(0x5DCAE0); called by BasePop_on_redraw
extern int  Buffer_write_strings_height(/*ecx*/ struct Buffer* self, void* list, int width, int flags); // addr: 0x005DAD70  observed  thiscall RET 0xC; flow-measure twin of Buffer_write_strings (flags&2 = keep cursor); nodes with payload flag 0 CONTINUE the previous line (g_wrap_width_used flow)
extern int  Buffer_write_raw_l(/*ecx*/ struct Buffer* self, const char* str, int x, int y, int len); // addr: 0x005DBD00  observed  thiscall; GDI TextOutA glyph writer (negative y clips safely); '~' starts an inline colour run
extern struct ScrollBar* ScrollBar_attach(int x, int y, int h, struct Win* parent, int a5); // addr: 0x00605890  observed  -> ScrollBar_init_inner(x,y,g_scrollbar_w,h,parent,a5,0); the TextScroll embedded-bar creator
extern void ScrollBar_set_pos(/*ecx*/ struct ScrollBar* self, int value); // addr: 0x00605D20  observed  thiscall RET 4; clamps to [+0xA20..+0xA24], +0xA28 inverts; redraw vtbl+0xF8
extern void ScrollBar_draw_2(/*ecx*/ struct ScrollBar* self); // addr: 0x006066F0  observed  vtbl+0x30; track fill + border box + thumb + grip tile + arrow sprite + [+0xA68] bevel boxes
extern void FlatButton_content_draw(/*ecx*/ struct FlatButton* self); // addr: 0x00607E50  observed  vtbl+0x30; label ellipsised when Buffer_text_width(label) > (R-L)-6 @0x6083C6; per-state face: centre sprite / box-sprite set [+0xAC8+state*4] / 9-slice sprites / bevel Buffer_box_2 loop ([+0xA90] x colours [+0xA88]/[+0xA8C], swapped when pressed); label via Buffer_wrap_cent_4
// field: TextScroll +0x1440 int bar_min   ; +0x1444 bar max ; +0x1460 bar page  (= the EMBEDDED ScrollBar's +0xA20/+0xA24/+0xA40; TextScroll_finish writes max = NODE count, page = visible-1)
// field: TextList +0x8 head node ; +0xC cursor ; +0x10 count ; +0x14 cur idx   node: +0x8 payload* +0xC next (CIRCULAR); payload: +0x4 char* str, +0x8 flags (file ^ prefixes: 1 paragraph, 2 centered, 3 title font; 0 = flow CONTINUATION of the previous line)
extern int  g_popup_body_bottom;               // addr: 0x009B8CE8  observed  Y-bottom of the last popup body-text draw (= Buffer_write_strings return), stored by BasePop_on_redraw; the ACTUAL drawn text bottom (vs the under-counted measure [popup+0x30d4])
extern int  g_popup_dialog_x;                  // addr: 0x009B8CEC  observed  dialog child-area x; written 0x604292/0x604ca1/0x604e0e (margin-sum variants), read 0x602b78 in BasePop_exec_3 when [popup+0x21cc] < 0
extern int  Buffer_text_width(struct Buffer* self, const char* str);           // addr: 0x005DC790  thinker   -> Buffer_text_width_2
extern int  Buffer_text_width_2(struct Buffer* self, const char* str, int len); // addr: 0x005DC7C0  thinker  thiscall
extern int  Buffer_text_height(struct Buffer* self);                           // addr: 0x005DCA80  thinker
extern int  Buffer_text_line_height(struct Buffer* self);                      // addr: 0x005DCAB0  thinker   row-pitch source
extern void Buffer_write_multi_font_raw_l(struct Buffer* self, const char* str, int x, int y, int len); // addr: 0x005DCAE0  thinker  thiscall
extern int  Buffer_wrap_height(const char* str, int width);                    // addr: 0x005DC360  observed  thiscall RET 8 ecx=buffer; wrapped-text height = n_lines * font line metric (f0>=0 ? f4+f0 : lh)
extern void GraphicWin_local_to_screen(struct GraphicWin* self, int* x, int* y); // addr: 0x005ED240  observed  thiscall RET 8; adds +0x13C/+0x14C origins recursively up the +0xC4 parent chain
extern int  Buffer_wrap_2(struct Buffer* self, const char* str, RECT* rect);   // addr: 0x005DD530  observed  thiscall RET 8; wraps str into rect: first line at (rect.left, rect.top), line pitch = Font.line_pad>=0 ? cap_h+line_pad : cell; -> wmfr_l
extern void Buffer_wrap_cent(struct Buffer* self);                             // addr: 0x005DBA30  observed
extern char* Buffer_find_line_break_l(const char* str, int* budget, int len);  // addr: 0x005DC410  observed  thiscall RET 0xC; fmt codes { } [ ] $ =; 0 = str fits budget, else break ptr
extern int  Buffer_wrap_height_flying(const char* str, int width);             // addr: 0x005DDDA0  observed  thiscall(ecx=Buffer) RET 8; content-height accumulation; stashes width -> g_wrap_width_budget, then calls _flying_2
extern int  Buffer_wrap_height_flying_2(const char* str);                      // addr: 0x005DDDE0  observed  thiscall(ecx=Buffer) RET 4; consumes g_wrap_width_budget / g_wrap_width_used
extern int  g_wrap_width_budget;                                               // addr: 0x009B3A98  observed  wrap pixel budget set by Buffer_wrap_height_flying
extern int  g_wrap_width_used;                                                 // addr: 0x009B3A9C  observed  running consumed width within the current wrapped line
extern int  Buffer_wrap_height_flying_flush();                                 // addr: 0x005DDEF0  thinker
extern int  Buffer_sync_to_palette(struct Buffer* self, struct Palette* pal);   // addr: 0x005DE8F0  thinker   thiscall RET 4; if pal gen (+0x400) != buf +0x4a4: copies 256 entries -> buf +0xA4 as RGBQUAD (via Palette_get_rgbquad) + updates the DIB color table (vtbl+4); called on GraphicWin+0x444 draw-context setup
extern int  Palette_get_rgbquad(/*ecx*/ struct Palette* self, void* dst, int start, int count); // addr: 0x005FE560  observed  thiscall RET 0xC; PALETTEENTRY (r,g,b,flags) -> RGBQUAD (b,g,r,0); ret 3 dst NULL / 7 HPALETTE 0x9B8178 NULL

// ============================================================================
// GraphicWin (window draw surface)
// ============================================================================
extern void GraphicWin_ctor(struct GraphicWin* self);                          // addr: 0x005D4CF0  thinker   on malloc(0xA14) block
extern int  GraphicWin_init(struct GraphicWin* self, int x, int y, int w, int h, char* name, int flags, struct Win* parent, struct Menu* menu, struct BorderSizing* border); // addr: 0x005D4EF0  thinker  thiscall RET 0x24; Win_init + Buffer_init(w,h) at self+0x444; SEH prologue
extern void GraphicWin_init_2();                                               // addr: 0x005D50A0  observed  variant -> GraphicWin_init
extern void GraphicWin_clear(struct GraphicWin* self, int color);              // addr: 0x005D5250  observed  thiscall RET 4; flags+0x98 bit 0x80000 && parent -> Buffer_copy_4 parent-canvas restore @0x5D52F2, else Buffer_fill_2(canvas, color) @0x5D5339 (BaseWin_init clears key-9 via this @0x41F500); the fill honours the canvas's CURRENT clip (+0x30 rect) only
extern void GraphicWin_fill_3(struct GraphicWin* self, int X, int Y, int W, int H, int color); // addr: 0x005D5440  thinker  thiscall
extern void GraphicWin_soft_update(struct GraphicWin* self, int X, int Y, int W, int H); // addr: 0x005D5720  observed  RET 0x10; clips to self+0x474, GDI-blits
extern void GraphicWin_redraw(struct GraphicWin* self);                        // addr: 0x005D5A70  observed  generic; guard flag +0x1A0 bit0, callback +0xA10, draw vtable[0x30], overlay_nonclient, then InvalidateRect of +0x474; = FlatButton vtbl+0xF8
extern void GraphicWin_soft_update_2(struct GraphicWin* self);                 // addr: 0x005D5890  thinker   thiscall; soft-update of the whole window rect
extern void GraphicWin_soft_update_3(struct GraphicWin* self, RECT* rect);     // addr: 0x005D5930  thinker   thiscall RET 0x04; InvalidateRect of window screen rect on HWND @0x9B7B28 — NO blit
extern void GraphicWin_on_paint(struct GraphicWin* self, RECT* clip);          // addr: 0x005D5CF0  observed  thiscall; default vtbl+0x124: blits own buffer +0x444 -> g_screen_buffer via Buffer_draw_2(1/1); gates parent!=0 && flags+0x98 bit 0x20; clips vs parent +0x14C (client child) / +0x13C (nonclient child, +0x98 high bit)
extern int  Win_update_screen(RECT* rect, struct Win* only);                   // addr: 0x005F7320  thinker   cdecl; walks z-list g_win_zlist top-down, per window: flags+0x9C bit0 + Win_is_visible(parent) then vtbl[+0x128 if +0x9C bit2] and [win+0xA8]->vtbl+0x124(rect)
extern void GraphicWin_present(struct GraphicWin* self, RECT* rect);           // addr: 0x005D56B0  observed  thiscall RET 4; rect NULL = whole window (+0x474..+0x480); Win_draw_rect -> Win_update_screen -> Win_flip_rect_2
extern void GraphicWin_present_default(struct GraphicWin* self);               // addr: 0x00404290  observed  thiscall; default vtbl+0xFC = GraphicWin_present(self, NULL)
extern void Win_draw_rect(RECT* rect);                                         // addr: 0x005F74A0  observed  cdecl; composites the z-list into g_screen_buffer for rect then Win_flip_rect_2
extern void Win_flip_rect_2(struct Win* self, RECT* rect);                     // addr: 0x005ECFE0  observed  thiscall RET 4; rect in place local -> screen: += rRect1.LT + rRect2.LT (+0x13C/+0x140, +0x14C/+0x150); flags&0x20 && parent: parent chain via 0x5ED240
extern void Win_flip_rect(RECT* rect);                                         // addr: 0x005EFD20  observed  cdecl; rect NULL = whole screen; IntersectRect with g_flip_clip; g_screen_buffer -> display BitBlt @0x5F018B (PRACX PRACXWindowBitBlt)
extern void (*g_flip_pre_hook)(void);                                          // addr: 0x009B7A48  observed  called at Win_flip_rect entry when non-NULL
extern int  g_flip_enabled;                                                    // addr: 0x009B7A50  observed  pending-flip flag: set per queued dirty rect, cleared on flush; Win_flip_rect skips when 0
extern RECT g_flip_clip;                                                       // addr: 0x009BC2D0  observed  Win_flip_rect IntersectRect clip (0,0,0,0 = none)
extern void* g_screen_hdc;                                                     // addr: 0x009B7B2C  observed  HDC from GetDC(g_main_hwnd) cached across nested flips
extern int  g_screen_hdc_refs;                                                 // addr: 0x009B3AB0  observed  nesting count for g_screen_hdc
extern HWND g_main_hwnd;                                                       // addr: 0x009B7B28  observed  GetDC arg in Win_flip_rect
extern struct Sprite* g_cursor_on_screen;                                      // addr: 0x009B7A2C  observed  the software cursor's sprite now drawn (Win_update_cursor; PaintMain blits it 1:1)
extern struct Buffer g_cursor_save_under;                                      // addr: 0x009B6F08  observed  the software cursor's save-under; Buffer_init to the sprite canvas on a sprite change
extern int  Win_is_visible(struct Win* self);                                  // addr: 0x005F7E90  thinker   thiscall
extern void GraphicWin_compute_min_size(struct GraphicWin* self);             // addr: 0x005D7030  observed  min w/h from frame corner sprites; early-returns for buttons
extern void slide_show(struct GraphicWin* win, int flags);                     // addr: 0x0045D440  thinker   cdecl; in-game slide-window painter: settled rail strips via Sprite_draw_2 1/1 (sites 0x45D82C/0x45D851/0x45D875/0x45D8A9) into win+0x444; animation loop draws them to SCREEN buf 0x9b7490 (sites 0x45D6BA/0x45D6DD/0x45D6FF/0x45D728); window ptr [ebp+8], rect L/T/R/B at [ebp-0x1c..-0x10]
extern void slide_hide(struct GraphicWin* win, int flags);                     // addr: 0x0045D970  observed  cdecl; slide-DOWN close animation; rail strips to SCREEN buf at 1/1 (sites 0x45DC86/0x45DCA9/0x45DCCE/0x45DCF9); window ptr in ESI ([ebp+8] reused as step counter), rect at [ebp-0x1c..-0x10]; common exit 0x45DE5A
extern void Buffer_set_clip(struct Buffer* self, RECT* rect);                  // addr: 0x005D8000  thinker   thiscall; sets the buffer clip rect (slide_show/hide clip the animation draws to the window rect via it)
extern struct Sprite g_rail_sprite_l_outer;                                    // addr: 0x007CFFC4  observed  15x529 left-outer side-rail chrome strip (fixed height; 4 consecutive 0x2C Sprite structs)
extern struct Sprite g_rail_sprite_l_inner;                                    // addr: 0x007CFFF0  observed  8x529 left-inner side-rail chrome strip
extern struct Sprite g_rail_sprite_r_inner;                                    // addr: 0x007D001C  observed  8x529 right-inner side-rail chrome strip
extern struct Sprite g_rail_sprite_r_outer;                                    // addr: 0x007D0048  observed  15x529 right-outer side-rail chrome strip

// ============================================================================
// Font system
// ============================================================================
extern void  Font_ctor(struct Font* self);                                     // addr: 0x00618EA0  thinker   thiscall
extern void  Font_init(struct Font* self, const char* name, int size, int flags); // addr: 0x00618F40  thinker  thiscall; face = the name string passed (TechWin: g_hud_font_name "Arial"; popup pool: "Arial Narrow"); flags 1 bold, 2 italic
extern struct Font* find_font(int size, int variant);                          // addr: 0x005882F0  observed  cdecl; returns font_table_v0 + idx*0xA0 + variant*0x28 (idx = nearest size in font_size_table)
extern int Font_width(struct Font* self, const char* str);                     // addr: 0x00619280  observed  thiscall(ecx=Font); pixel width of str with THAT font (chop/fit loops measure via the fn-local font, not the buffer's)
extern struct Font font_table_v0[12][4];                                       // addr: 0x0093FC58  observed  cached Font rows (one per font_size_table size), 4 variants x 0x28 each (row stride 0xA0)
extern struct Font* g_text_font_v0;                                            // addr: 0x00945770  observed  config_popups nearest-size pick, variant 0 (interlude body text)
extern struct Font* g_text_font_v1;                                            // addr: 0x009457FC  observed  same size row, variant 1
extern struct Font* g_text_font_v2;                                            // addr: 0x009457F8  observed  same size row, variant 2
extern void  config_popups(void);                                              // addr: 0x00588AA0  observed  builds font table + popup default fonts
extern void  popups_normal(void);                                              // addr: 0x00588460  observed  installs popup default fonts (size 16); also rewrites g_menu_font from g_popup_menu_font_src @0x5886C1
extern struct Font* g_popup_font_native;                                       // addr: 0x009403D8  observed  the native find_font(16,0) Font* popups_normal loads; stays native under the g_pf0 rewires (thunk_t16_measure_native's measure font)
extern void  Dialog_set_def_dialog_font(struct Font* f0, struct Font* f1, struct Font* f2); // addr: 0x00609D20  observed  cdecl; stores the def-dialog font triple
extern struct Font* g_def_dialog_font0;                                        // addr: 0x009B8EC0  observed  def-dialog font triple -> Dialog +0x70/74/78 at build
extern struct Font* g_def_dialog_font1;                                        // addr: 0x009B8EC4  observed
extern struct Font* g_def_dialog_font2;                                       // addr: 0x009B8EC8  observed
// field: Font +0x0  int   line_pad      -1 = none; Buffer_text_line_height = cap_h+line_pad if >= 0 else cell
// field: Font +0x8  HFONT hfont
// field: Font +0xC  int   cell          tmHeight + tmExternalLeading (Font_init 0x618F40)
// field: Font +0x10 int   cap_h         tmAscent - tmInternalLeading (Buffer_text_height)
// field: Font +0x14 int   int_leading   tmInternalLeading
// field: Font +0x18 int   ascent        tmAscent
// field: Font +0x1C int   descent       tmDescent
extern char* Font_find_line_break_l(const char* str, int* budget, int len);    // addr: 0x00619370  observed  thiscall(ecx=Font) RET 0xC; GDI GetTextExtentPoint32A word-fit; writes remaining budget
extern struct Font g_popup_title_font;                                         // addr: 0x007CFE8C  observed  = MainWin +0x2166C fontA14, Font_init("Arial",14,1); cell 16
// Font struct (size 0x28) -- fields filled by Font_init from GDI TEXTMETRICA (lfHeight = -size):
// field: Font +0x0C int cell_height   tmHeight + tmExternalLeading (line pitch; native 20 @ size16; ~47 @ size40)
// field: Font +0x10 int cap_height    tmAscent - tmInternalLeading (writers: y = rect.T + (H - cap)/2, then raw_l adds it back on a TA_BASELINE DC)
// field: Font +0x00 int line_pad      -1 default; >=0 -> line height = +0x10 + this
// field: Font +0x04 int flags         bit0 = keep HFONT/resource on re-init
// field: Font +0x08 HFONT hfont
// field: Font +0x24 char* resource_path  RemoveFontResourceA target
// field: Font +0x14 int internal_lead tmInternalLeading
// field: Font +0x18 int ascent        tmAscent
// field: Font +0x1C int descent       tmDescent

// ============================================================================
// Popup / BasePop / Dialog pipeline (shared by every pop-up)
// ============================================================================
extern int  Popup_start(struct Popup* self, const char* filename, const char* label, int a4, char* a5, int a6, struct GraphicWin* a7); // addr: 0x00406380  thinker  thiscall; universal modal entry (133 callers); TechWin_exec @0x4867F0 passes (0x9B8AA8, label|"TECHNOLOGY", -1, 0, 2, 0)
extern void Popup_show();                                                       // addr: 0x00404920  observed  calls slide_show(this, 0) @0x4049D3 ONLY when [+0xa14]==0 && console Win_is_visible && type [+0x30ac]/10000 in {0,5} (type 1000 -> plain Win_show; everything else incl. the type-2/6 ornate family -> no slide/rails); positions box via Win_move(((ScreenWidth-[+0x4c4])+0x20)/2, ([+0x4c8]-g_console_strip_height)+ScreenHeight) @0x4049C1 -- the +0x20/2 = +16px right nudge (add eax,0x20 @0x4049B8) offsets the asymmetric box margins [+0x21b0]/[+0x21b4]
extern void Popup_hide();                                                       // addr: 0x00404A80  thinker   calls slide_hide(this, 0) @0x404AED
extern void Popup_close();                                                      // addr: 0x00404900  thinker
extern int  popb(const char* label, int flags, int sound_id, const char* pcx_filename, struct Sprite* a5); // addr: 0x0048C650  thinker  cdecl; picture popup; Console_focus on the base unless MPREF 0x4
extern int  drop_range(int faction);                                           // addr: 0x00500320  observed  cdecl; airdrop limit: unlimited with the orbital-insertion tech (Rules+0x9497C8 via has_tech) or the Space Elevator, else Rules_max_airdrop_rng
extern int  Rules_max_airdrop_rng;                                             // addr: 0x00949740  observed  Rules->max_airdrop_rng_wo_orbital_insert (drop_range's finite limit; action_airdrop's DROPRANGE number)
extern int  zoc_any(int x, int y, int faction);                                 // addr: 0x005C89F0  thinker  cdecl; any non-pact unit or base on a neighbour, no visibility test
extern int  zoc_veh(int x, int y, int faction);                                 // addr: 0x005C8AC0  thinker  cdecl; land ZOC, no visibility test
extern int  zoc_sea(int x, int y, int faction);                                 // addr: 0x005C8BA0  thinker  cdecl; per unit: seen bit, else single-player and no VFLAG_INVISIBLE
extern int  zoc_move(int x, int y, int faction);                                // addr: 0x005C8D40  thinker  cdecl; 0 on an owned base tile, else zoc_sea; action_airdrop applies it to non-combat units only
extern int  popp(const char* filename, const char* label, int a3, const char* pcx_filename, void* fn); // addr: 0x0048C0A0  thinker  cdecl; script popup with a picture (GOVERNOR: "council_sm.pcx" from 0x428542)
extern void* Popup_vtbl;                                                       // addr: 0x006695C8  observed  Popup vtable (heap popp popups + Popup_ctor statics); +0x4=Popup_show +0x8=Popup_hide +0x20=popup_sb_create +0x24=popup_sb_remove +0x168=Popup_calculate_dimensions
extern void* Popup_sub_vtbl;                                                   // addr: 0x0066A8A8  observed  Popup-derived class vtable (dtor 0x421640; stack-local instances in BaseWin_ctor 0x40924B + net UI 0x47C57B..); slots +0x4..+0x180 identical to Popup_vtbl
extern void* BasePop_vtbl;                                                     // addr: 0x006698D4  observed  BasePop vtable (BasePop_ctor 0x600860 store @0x6009E1); +0xC0/+0xC4 = stub 0x404260 (only Popup overrides them)
extern void Popup_ctor(/*ecx*/ struct Popup* self);                            // addr: 0x004048A0  observed  thiscall; BasePop_ctor + ScrollBar_ctor(this+0x3230); vtbl store 0x6695C8 @0x4048D9
extern void Popup_on_scroll(/*ecx*/ struct Popup* self, int id, int value);    // addr: 0x00406B70  observed  thiscall RET 8; vtbl+0xC0 (chevron notify): virtual-base forwarder -> [popup+0x2358] element vtbl 0x669BE8+0xC0 -> 0x612F80 -> ListBox_on_scrolling when [popup+0x2350]==2
extern void Popup_on_scroll_drag(/*ecx*/ struct Popup* self, int id, int value); // addr: 0x00406BA0  observed  thiscall RET 8; vtbl+0xC4 twin of Popup_on_scroll
extern void ListBox_on_scrolling(/*ecx*/ void* listbox, int id, int value);    // addr: 0x0060C5D0  observed  thiscall (this = popup+0x2218); id -1: first row [popup+0x21E8] = value; id -2: page*value; [0x9B8DDC] set -> also moves the selection; redraw vtbl+0xF8 / touched rows
extern void ListBox_set_hover(/*ecx*/ void* listbox, int x, int y);            // addr: 0x0060CBC0  observed  thiscall RET 8; vtbl thunk jmp@0x60CF83 + call@0x612BC0; hovered slot from x/y (grid path cols>1, item-walk path cols==1), redraws old+new rows via ListBox_draw_item; slot bounded by count only (baked clamp @0x60CC29/0x60CD44 = group listbox_hover_clamp)
extern void ListBox_clear_hover(/*ecx*/ void* listbox, int a, int b);          // addr: 0x0060CE10  observed  thiscall RET 8 (args unused); vtbl thunk jmp@0x60CF83 + call@0x612B20; Dialog+0xA8 := -1 then element vtbl+0xF8 redraw
// field: ListBox(Dialog part = ListBox part + [[element]+8]) -0x10 int list_top      y origin of the rows (set_hover subtracts it)
// field: ListBox(Dialog part) -0x8  int list_left     x origin (grid path)
// field: ListBox(Dialog part) -0x4  int cell_gap      added to cell w / row h in the hover divisions
// field: ListBox(Dialog part) +0xC  int cols          1 = single-column item-walk path (per-item line counts), >1 = fixed grid
// field: ListBox(Dialog part) +0x10 int rows          visible rows per column = the draw loop bound (@0x60C566/0x60C5B7)
// field: ListBox(Dialog part) +0x1C int cell_w        grid path column pitch (+ cell_gap)
// field: ListBox(Dialog part) +0x20 int row_h         row pitch (+ cell_gap), x per-item line count on the walk path
// field: ListBox(Dialog part) +0x7C void* items_head  linked list head; +0x80 cursor node, +0x88 cursor index
// field: ListBox(Dialog part) +0x84 int count         item count
// field: ListBox(Dialog part) +0xA4 int selected      selected item (-1 none)
// field: ListBox(Dialog part) +0xA8 int hover         hovered item (-1 none)
extern struct ScrollBar* popup_sb_create(/*ecx*/ struct Popup* self);          // addr: 0x00406260  observed  thiscall; the ONLY parent-setter of the rail +0x3230: ScrollBar_init_inner(clientW-0x2B, 0x15, 0x18, h, popup, -1, 1), hide, rail_slide_in if visible; reached via element vtbl+0x18 0x407150 -> ListBox_scroll_create_cb 0x613220 (type 2 + style 0x40)
extern int  g_key_scroll_selects;                                              // addr: 0x009B8DDC  observed  1 = ScrollBar_on_key path (scroll drags the selection), 0 = chevron/drag (pure scroll); ListBox_on_scrolling reads it
extern void* FileDlg_vtbl;                                                     // addr: 0x00669EC8  observed  LOAD/SAVE dialog vtable (FileDlg_ctor 0x407350); ScrollBar at +0x3DD8; +0xC0 0x4080E0 +0xC4 0x408110; on_key 0x407D10
extern void* TextScroll_vtbl;                                                  // addr: 0x0066ADC8  observed  chat log / Datalinks text scroller (TextScroll_ctor 0x629110); ScrollBar at +0xA20; +0xC0 0x629D20 +0xC4 0x629D40; on_key stub 0x406A80
extern void* PrefSubDlg_vtbl;                                                  // addr: 0x0066C3D8  observed  dialog ctor'd at 0x5C8DA0 (opened from PrefWin_on_command @0x49142D); ScrollBar at +0xEF0; +0xC0 0x5C9390 +0xC4 0x5C93A0
// field: Win +0x43C  struct ScrollBar* scroll_vert   (heap bar when style flag 8, else the rail via element vtbl+0x18 @0x5EC394); key router 0x5F61CD offers keys to it; Win_set_vert_range 0x5F85B0 / Win_set_vert_paging 0x5F85E0 dispatch here
// field: Win +0x440  struct ScrollBar* scroll_horz
// field: Popup +0x2358 struct Win list_win     element-interface window (vtbl 0x669BE8); its +0x43C = popup+0x2794 = the live vertical ScrollBar* (0 when the list fits)
// field: Popup +0x21E8 int list_first_row
// field: Popup +0x21EC int list_visible_rows
// field: Popup +0x2E3C int list_item_count
// field: Popup +0x2E5C int list_selected
extern void* NetMessage_vtbl;                                                  // addr: 0x0066CB60  observed  NetMessage vtable (NetMsg_ctor 0x47AD3E); Popup family (slot +0x4 = Popup_show)
extern void* TutWin_vtbl;                                                      // addr: 0x0066DD84  observed  TutWindow vtable (TutWin_ctor 0x4BA6BF); Popup family (slot +0x4 = Popup_show)
extern struct Popup* Popup_alloc();                                            // addr: 0x00404FB0  thinker   cdecl; new Popup (0x537C) + Popup_ctor -> heap popup object (vtable Popup_vtbl)
extern int  ListBox_scroll_create_cb(/*ecx*/ void* elem);                      // addr: 0x00613220  observed  fastcall; ListBox element ([elem-8]==2, flag 0x40) -> owner Popup [dlg+0x7C]->vtbl+0x20 (popup_sb_create); returns Scroll*
extern int  ListBox_scroll_delete_cb(/*ecx*/ void* elem, void* sb);            // addr: 0x0060CF20  observed  thiscall RET 4; owner Popup [dlg+0x7C]->vtbl+0x24 (popup_sb_remove)
extern void Popup_calculate_dimensions(struct BasePop* self);                  // addr: 0x00404B10  observed  fastcall; wraps BasePop_calculate_dimensions; ART popups only ([+0x2144]!=0): Dialog[+0x2c] = min(Dialog[+0x5c]?:[+0x2c] + art_w*[+0x3104]/[+0x3108] + padx, ScreenWidth-0x16E); art mul/div 0x404B6F/0x404B77, clamp LEA 0x404BC4; tail 0x404EBD clamps in-game (mode 0/5, console visible, [+0xa14]==0) box_h [+0x30c0] to min 300, shortfall -> footer [+0x30ec]
extern void Popup_on_adjust_button_width(struct BasePop* self);              // addr: 0x00405020  thinker   thiscall; Popup vtbl+0x174
extern void sprite_draw_func(struct Sprite* sprite, struct BasePop* self, int a3, int a4, int x, int y); // addr: 0x00404860  observed  cdecl; default [popup+0x3168] art draw; Sprite_draw_2(win+0x444, key [sprite+8], x-5, y-6, 1, 1) — the -5/-6 are NATIVE constants applied after the seed sums (x=[30e0]+[30f0]+[21c8], y=[30e8]+[30e0])
extern void BasePop_ctor(struct BasePop* self);                                // addr: 0x00600860  observed
extern int  BasePop_close(struct BasePop* self);                               // addr: 0x00600F00  thinker   thiscall; resets +0xA14 from g_popup_def_ext_win
extern int  SpriteBox_sprite(/*ecx*/ void* self, struct Sprite* sprite, char* label, int a4);   // addr: 0x006108E0  thinker  thiscall RET 0xC; appends one sprite item
extern int  SpriteBox_close(/*ecx*/ void* self);                              // addr: 0x00610280  thinker  thiscall; clears the item list
extern void BasePop_init(struct BasePop* self, unsigned flags, int a3);        // addr: 0x006015B0  thinker   thiscall; Spot_init
extern void BasePop_start(struct BasePop* self);                               // addr: 0x00601BF0  thinker   thiscall; parses script -> items
extern void BasePop_calculate_dimensions(struct BasePop* self);                // addr: 0x00603800  thinker   fastcall; sizes popup; calls Dialog_dims_dispatch; body wrap budget ebx = [+0x30bc]-2*[+0x30e0]-[+0x21c8]-[+0x30d8] @0x603d82, passed to Buffer_wrap_height_flying @0x603e42/0x603f3d; accumulates content_h [+0x30d4]
extern int  veh_pick(int veh_id, const char* label, int flag);                  // addr: 0x0048D0D0  thinker  cdecl; unit-stack picker popup (#PICKEDIT etc.)
extern void veh_sprite_draw();                                                 // addr: 0x0048CEB0  thinker   cdecl; veh_pick's OptionList custom unit draw fn
extern void BasePop_exec_3(struct BasePop* self);                              // addr: 0x00602600  observed  shows popup + modal loop; SEH prologue; 111 callers
extern void BasePop_set_loc(struct BasePop* self, int x, int y);               // addr: 0x00601B80  observed  thiscall; sets popup top-left screen pos. Faction quote box placed via thumb_routine BasePop_set_loc(5,0x136) @0x589A02 (below the picker)
extern void thumb_routine(int faction_id);                                     // addr: 0x005898A0  observed  shows the faction-advisor quote popup (g_faction_quote_popup) during Choose Your Factions; BasePop_set_loc(5,310)+BasePop_exec_3
extern void Dialog_dims_dispatch(struct BasePop* self);                        // addr: 0x006132A0  observed  switch on dialog type [+0x60] -> per-type calc
extern int ListBox_calculate_dimensions(struct BasePop* self);                 // addr: 0x0060A1E0  thinker   fastcall; computes visible-rows [+iface+0x58] = (boxH[+0x30] - inset[+0x3c] - [+0x38] + gap[+0x44]) / rowH[+0x68]; scrollbar engages iff [+0x58]*cols[+0x54] < count[+8]. rowH[+0x68]=rowStride[+0x48] (faction +0x8704). Called via Dialog_dims_dispatch/ListBox_attach/ListBox_update_changes
extern int ListBox_update_changes(struct BasePop* self);                       // addr: 0x0060C9B0  thinker   fastcall; recalcs dims, sets Win_set_vert_range(count-1)/paging(visible-1) -> the scrollbar
extern int ListBox_attach(int a1, int a2, int a3, int a4);                     // addr: 0x0060A670  thinker   fastcall
extern void ListBox_set_selected_pos(int pos, int a2);                         // addr: 0x0060A020  thinker
extern void ListBox_close(/*ecx*/ void* self);                                 // addr: 0x00609F20  observed  thiscall; resets the list (re-seeds text pad +0x2C from g_listbox_text_pad_default)
extern int  g_listbox_text_pad_default;                                        // addr: 0x006970E4  observed  ListBox ctor/close default text pad (2)
// field: ListBox +0x2C int text_pad   ListBox_draw_item insets each column text rect by pad+1 per side
extern void Dialogs_item(struct BasePop* self, const char* str, int a3);       // addr: 0x00612A70  thinker   thiscall; dispatch by [+0x180]
extern int  ListBox_item(/*ecx*/ void* self, const char* str, int a3);         // addr: 0x0060C920  observed  thiscall RET 8; TYPE-2 adder: appends + word-wraps one line
extern int  Dialog_item(/*ecx*/ void* self, const char* str, int a3);          // addr: 0x00609990  observed  thiscall RET 8; types 1/4/8/16 adder: line count := 1
extern bool Popup_on_draw_background(struct BasePop* self);                    // addr: 0x00405C80  observed  fastcall; titled popups use ELSE branch ([+0xa14]==0): title-bar height 0x1a@0x40602e, title font push g_popup_title_font@0x40609d, title text Buffer_write_cent_l_7@0x4060e2; box-sprite draws: window backdrop d690@0x405f77 (type [+0x30ac]/10000 == 6 or 2 -> ORNATE def &0x6846b0 instead, title insets 9/9; type 0/5 + console visible -> the d690insets delta block L+0x17/R-0x37/B+5 @0x405F24), title d5a0@0x406048+d618@0x406078, button-block frame d528@0x406154, outer-union frame d5a0@0x406238 (the ITEM-AREA frame: rect = content anchor +-3, w/h from Dialog[+0x5c]/[+0x60])
extern void BasePop_on_redraw(struct BasePop* self);                           // addr: 0x00604AB0  observed  fastcall; draws popup BODY via Buffer_write_strings(self+0x860, X, Y, width)@~0x604df5: X=[+0x30e0]+[+0x30f0]+[+0x21c8]+[+0x30d8] (=inner d528.left+3), Y=[+0x30e8]+[+0x30e0], width=-2*[+0x30e0]-[+0x30f4]+[+0x30bc]-[+0x30d8]-[+0x30f0]-[+0x21c8]; body font=[+0x3110] set by Buffer_set_font@0x604dxx; rendered text-x IS the [esp+8] stack arg (proven by +200px diagnostic), not a layout rect
extern struct BasePop g_faction_quote_popup;                                   // addr: 0x009403E0  observed  the static faction-advisor portrait+quote popup object (Choose Your Factions); stable across runs; esi==this gates thunk_scale_boxw/thunk_faction_bodyfont/thunk_faction_textmargin
// field: BasePop +0x3110 Font* body_font   ; param_1[0xc44]; popup body-text font (native cell-h 20); item-B scale target
// field: BasePop +0x30bc int box_width      ; param_1[0xc2f]; popup box width (feeds body wrap budget)
// field: BasePop +0x30d8 int content_off_x   ; param_1[0xc36]; +X to text/frame, -1 to wrap width
// field: BasePop +0x30e0 int content_pad      ; param_1[0xc38]; +1 to text X & frame.left & Y, -2 to wrap width
// field: BasePop +0x30e8 int content_top       ; param_1[0xc3a]; +Y (with +0x30e0)
// field: BasePop +0x30f0 int content_left_marg ; param_1[0xc3c]; +X to text/frame.left, -1 to wrap width
// field: BasePop +0x30f4 int content_right_marg; param_1[0xc3d]; -1 to wrap width
extern int Popup_on_dialog_item_back_draw(struct BasePop* self, struct GraphicWin* buf, int a3, int idx, int* rect); // addr: 0x00405B20  observed  thiscall; per-OPTION row back draw: checkbox sprite (FUN_005e4b4a) + per-option frame Buffer_box_sprite(&rect, d960+idx*0x28)@0x405bf6
extern void Dialog_init();                                                     // addr: 0x00609150  thinker
extern void Dialog_set_type(/*ecx*/ void* self, int type, void* parent_win, int x, int y, unsigned flags); // addr: 0x00612970  observed  thiscall; type&0x1f -> Dialog[+0x180] + per-type setup switch; SOLE caller BasePop_exec_3 0x602bfe; arg2 = popup[+0xa3c] = PARENT WINDOW (NOT a font — forwarded verbatim as the element attach parent, e.g. push @0x612a0f -> OptionList_attach)
extern int  OptionList_calculate_dimensions(/*ecx*/ void* self);               // addr: 0x00610970  observed  thiscall on Dialog subobj+0x70 (adjustor [vtbl+8]=-0x70 -> fields on the Dialog base); Buffer_set_font(Dialog[+0x70..0x78]) then measures: [+0x5c]=max text w, [+0x54]/[+0x58]=max sprite w/h x elem[+0x1c]/[+0x20] (one ecx/edi load pair @0x610AE1 serves both divs), lineH @0x610b4c; pitch [+0x68]=gap[+0x44]+max(lineH,spriteH) @0x610b62; total [+0x60]=gap+pitch*visrows @0x610bcf
extern int  OptionList_attach(/*ecx*/ void* self, void* parent_win, int x, int y, unsigned flags); // addr: 0x00610540  observed  thiscall (self = Dialog+0xb14); calc_dims (call @0x610580) then row-window GraphicWin_init @0x6105ec with w=Dialog[+0x5c], h=Dialog[+0x60], parent=parent_win (stored -> Win+0x38; feeds the on_redraw background capture)
extern int  Dialog_type16_calc_dimensions(/*ecx*/ void* self);                // addr: 0x0060D380  observed  fastcall; type-16 measure; returns 0, 7 when no rows
extern int  Dialog_type16_attach(/*ecx*/ void* self, int a1, int a2, int a3, int a4); // addr: 0x0060D1F0  observed  thiscall RET 0x10; calc then row-window GraphicWin_init @0x60D299
extern void Dialog_on_redraw_dispatch(/*ecx*/ void* elem);                     // addr: 0x00612E00  observed  fastcall; per-type redraw switch on [elem-8]: 1->0x60FAB0, 2->ListBox_on_redraw, 4->0x612450, 8->OptionList_on_redraw, 16->0x60E220
extern void OptionList_on_redraw(/*ecx*/ void* elem);                          // addr: 0x00611380  observed  fastcall (elem = Win+0x8c); if parent=[Win+0x38]: BACKGROUND CAPTURE Buffer_copy_4(src=parent+0x444 canvas @ (x,y)=[vbase2-0x68/-0x64], dst=own canvas Win+0x444, own W/H) @0x6113D6, then OptionList_draw_item per row
extern int  OptionList_draw_item(/*ecx*/ void* elem, int idx);                 // addr: 0x00610C50  observed  thiscall; row bg Buffer_copy_4 (exactly pitch[+0x68] tall) + sprite recentered y += (pitch-sprHs)/2 + selection ring Buffer_box @0x610FE3 (bottom cluster @0x610FBC: y+1+pitch-3, the -3 = native row gap) + label Buffer_write_l_4; callers 0x611060/0x611380/0x611400
extern int  Dialog_type4_calc_dimensions(/*ecx*/ void* self);                  // addr: 0x00612150  observed  thiscall; dialog_type 4 (single text-entry, e.g. name prompt); adjustor +0xf8; measure font Dialog[+0x70]; total h -> [+0x60/+0x80]
extern int  Dialog_type4_attach(/*ecx*/ void* self, int parent, int x, int y, unsigned flags); // addr: 0x00611AF0  observed  thiscall; type-4 attach: calc dims, GraphicWin_init(x,y,Dialog[+0x5c],Dialog[+0x60]), EditLine_ctor/attach per row
// field: Dialog +0x7C  int   t4_label_w          type-4: widest row label, dialog font
// field: Dialog +0x80  int   t4_edit_w           type-4: widest edit text + 2*[+0x40], min 10
extern struct BasePop* g_pops_basepop;                                        // addr: 0x009BC078  observed  pops_18's ordinary popup object
extern struct BasePop* g_pops_basepop_ext;                                    // addr: 0x009BC074  observed  pops_18's anchored popup object (+0xA14 set in diplomacy)
// field: Dialog +0x44  int32 row_gap          inter-row gap; Dialog default 6 (0x69709c; PrefWin pages), popups 3 (Popup_calculate_dimensions)
// field: DialogItem +0x08 int line_count        type-16 calc 0x60D5FA: W / ([+0x2C]/cols - 2*[+0x40] - [+0x34]) + 1
extern int  Dialog_type16_calc_dimensions(/*ecx*/ void* self);                 // addr: 0x0060D380  observed  thiscall; dialog_type 16 = the QUIT-class multi-option grid; adjustor +0x44; +0xcc count gate (ret 7 if 0); row height [+0x68]=max(spriteH, Buffer_text_line_height) via the two calls @0x60d641/0x60d658 (patch popup_quit_type16_rowpitch redirects both to line_height); total [+0x60]=([+0x68]+gap[+0x44])*count[+0x58] @Site B 0x60d731 -> popup[+0x30c4] content_h -> row stride; draw loop's per-bar height also uses Buffer_text_line_height @0x60da0a; row width measure @0x60d5ce Buffer_text_width (site patched -> thunk_t16_measure_native), feeds d5c=max(xs,W+F)-F @0x60d618..0x60d6ec
extern void Dialog_type16_draw_rows();                                         // addr: ~0x0060D9xx  observed  type-16 option-row draw loop; builds per-row rect (w=Dialog[+0x64], h from Buffer_text_line_height 0x5dcab0 @0x60da0a) and calls item_back_draw via [item_vtbl+0x2c] @0x60da9a (ret 0x60da9d); blits row via Buffer_copy_4 @0x60dae3, icon via Sprite_draw_2 @0x60db3c; re-reads gap [D+0x44] @0x60d8d8 to rebuild pitch=[D+0x68]+gap @0x60d8f3 and offset each row top by gap>>1 @0x60d8ff (so the gap must be in the FIELD, not only in the calc's register)
extern void Dialog_type16_draw_item(/*ecx*/ void* elem, int idx, int pressed); // addr: 0x0060D750  observed  thiscall; row text left = x + Dialog[+0x34]; rows may span several lines
extern int  Dialog_type16_attach(/*ecx*/ void* self, int win, int x, int y, unsigned flags); // addr: 0x0060D1F0  observed  thiscall RET 0x10; calc (call @0x60d224, ecx=self-0xa30) then row-window GraphicWin_init @0x60d299 with w=[self+0x188]=Dialog[+0x5c], h=[self+0x18c]=Dialog[+0x60] (adjustor [vtbl+8]=0xb5c off self-0xa30 -> Dialog base = self+0x12c)
// field: Dialog +0x180 int32 dialog_type      ; 1 -> calc 0x60ED10 (text-elem/checkbox), 2 -> 0x60A1E0 (ListBox), 8 -> 0x610970 (option list), 4 -> 0x612150, 16 -> 0x60D380 (Dialog_dims_dispatch byte table 0x613310, dword targets 0x6132f8)
// field: Dialog +0x70  void* dlg_font         ; the dialog FONT TRIPLE +0x70/+0x74/+0x78 -> Buffer_set_font in OptionList_calc @0x6109c0 AND draw_item @0x610f3a — measure and draw use the SAME font (never mismatched; the 07-26 qdlg premise was wrong twice). Dialog_set_type is a pure dispatcher, it writes nothing here (07-31)
// field: OptListElem +0x1c int32 spr_num       ; elem = Dialog+0xb14; sprite display ratio numerator (native 1); reads: calc 0x610AE1, draw_item 0x610DF1 + selection box 0x610FCA (all scaled x g/16 by group popup_optionlist8_spritezoom)
// field: OptListElem +0x20 int32 spr_den       ; ratio denominator (native 1); scaled x16 at the same sites
// field: OptListElem +0x54 int32 max_spr_w     ; calc's max sprite W x num/den; draw_item label x = rowX + this + 4
// field: OptListElem +0x58 int32 max_spr_h     ; calc's max sprite H x num/den; pitch = gap + max(lineH, this)
// field: OptListElem +0x5c int32 max_text_w    ; calc's max Buffer_text_width over row labels
// field: OptListElem +0x60 int32 line_h        ; calc's Buffer_text_line_height of the dlg font
// field: OptListElem +0x64 void* custom_draw   ; if set, draw_item draws the sprite via this fn with SCALE_NUM/DEN_G armed (unit-stack picker portraits); else Sprite_draw_2(num,den)
// field: Dialog +0x2c  int32 min_width        ; min/word-wrap width (popup native 480); SHARED source — scale at read sites only
// field: Dialog +0x2c  == BasePop +iv3 +0x21fc  ; Dialog base = BasePop +iv3 +0x21d0, iv3 = [[BasePop+0x21d0]+8] (=0xba0)
// field: Dialog +0x5c  == BasePop +iv3 +0x222c  ; zeroed by Dialog_dims_dispatch default arm (dialog_type -1)
// field: Dialog +0xcc  int32 item_count       ; option/row count (type-1 count read [DR-0x968], type-8 [R-0x9d8] resolve here)
// field: Dialog +0x5c  int32 item_width       ; measured max row/text width; type-16 attach pushes it as the row-window GraphicWin_init w arg
// field: Dialog +0x64  int32 row_bar_width    ; drawn option-bar width (type-16 draw-loop rect right edge = [+0x64]+x)
// field: Dialog +0x40  int32 text_margin      ; per-side row text margin (type-8 [+0x64] = text w + 2*[+0x40] + sprite col, 0x610B6D)
// field: BasePop +0x2350 int32 dialog_type_req   -1 none; 1/2/4/16 by BasePop_init/BasePop_start; 8 = OptionList promotion
// field: BasePop +0x30c4 int32 list_reserve_h    type-2 list box height BasePop_calculate_dimensions lays the box out with (its ListBox calc @0x603B42)
// field: BasePop +0x2274 int32 spritebox_count   SpriteBox (+0x2240) item count
// field: SpriteBox +0x34 int32 item_count   item list (+0x24) count (+0x10)
// field: BasePop +0xa3c  void* attach_parent_win ; passed as Dialog_set_type arg2 and forwarded VERBATIM as the element-attach PARENT window (0x612a0f). The earlier "Font ~24px" reading was a MISIDENTIFICATION (root cause of the 07-26 type-8 crash — thunk_qdlg_font swapped it for g_pf0)
extern int  g_scrollbar_w;                                                     // addr: 0x009B8DD4  observed  list scrollbar width (20); Dialog_item wrap budget = Dialog[+0x2c] - this
extern void config_game();                                                     // addr: 0x00589D30  observed  game-setup controller (DIFFICULTY/USERULES/faction-pick); builds the faction window via FactionPickWin_build @0x58a604
extern void custom_planet(int a1, int a2);                                     // addr: 0x0058C2A0  thinker   planet-setup screen (6 ScreenWidth reads)

// ============================================================================
// TutWin (tutorial / directional-tooltip window -- a Popup/BasePop subclass; TUTOR-script popups with the pointer line)
// ============================================================================
extern struct TutWindow TutWin;                                                 // addr: 0x008C6E68  thinker   the global tutorial-window object (Popup_ctor'd; Thinker's GraphicWin typedef is a placeholder)
extern void TutWin_ctor(struct TutWindow* self);                               // addr: 0x004BA6B0  thinker   thiscall; calls Popup_ctor
extern int  TutWin_tut_win(struct TutWindow* self, struct Win* anchor, const char* label, int x, int y, struct Sprite* spr, unsigned flags, int x2, int y2); // addr: 0x004BDFE0  thinker  thiscall; popups_tutorial -> Popup_start("TUTOR",label) -> BasePop_exec_3 x2 -> popups_normal; returns with the window still shown (non-modal)
extern int  TutWin_tut_map(struct TutWindow* self, const char* label, int tx, int ty, int a5, struct Sprite* spr, int a7, int tx2, int ty2); // addr: 0x004BE650  thinker  thiscall; map-tile anchored variant (54 callers incl. Console_give_hints); MapWin_focus + tile->screen then tut_win
extern void TutWin_draw_arrow(struct TutWindow* self);                         // addr: 0x004BDEA0  thinker   fastcall; redraws the pointer line(s) each blink tick via Win_window_line_raw(.., color, width=2, style=PS_DOT) from +0x538C/+0x5390 -> +0x5384/+0x5388 (2nd line +0x539C..+0x53A0), gated on +0x53A4
extern void TutWin_on_button_clicked(struct TutWindow* self, int id);          // addr: 0x004BDCC0  thinker   thiscall; dismisses + clears the arrow state
extern void popups_tutorial(void);                                             // addr: 0x005888E0  observed  installs the TUTORIAL popup style: def string/dialog font = g_text_font_v0/v1/v2 (native-small), def button font, margins 3/3
extern void Win_window_line_raw(struct Win* self, int x, int y, int x2, int y2, int color, int pen_width, int pen_style); // addr: 0x005F2AC0  observed  thiscall; GDI CreatePenIndirect line (x2,y2)->(x,y); arg7=lopnWidth.x, arg8=lopnStyle (PS_*; 5=PS_NULL draws NOTHING; TutWin passes 2,PS_DOT)
extern void FlatButton_content_draw(struct FlatButton* self);                  // addr: 0x00607E50  observed  fastcall; 9-slice bar + label draw; state idx [+0xAB8] (0 normal/1 hover/2 pressed fallback chain); thunk_btn_shrink detour sits at +0x2F (0x607E7F)
extern void FlatButton_reset_faces(struct FlatButton* self);                   // addr: 0x00607DA0  observed  thiscall; vtbl+0x168 (BaseButton_init's first call): +0xAC8/+0xAD4 sets = 0, +0xAE0.. = g_default_btn_frame_sprites, +0xAB8 = -1, +0xABC label colours = -1
extern void TutWin_tour(struct TutWindow* self);                                // addr: 0x004BC6E0  thinker   thiscall; tour dispatcher on +0x53C0 (1 tour1, 5 0x4BB380, 6 tour6, 7 0x4BAF20, else the map TOUR* steps)
extern void TutWin_tour1(struct TutWindow* self);                               // addr: 0x004BB7A0  thinker   thiscall; base-screen tour (TOUR1* labels)
extern void TutWin_tour6(struct TutWindow* self);                               // addr: 0x004BAA70  observed  thiscall; DRONERIOTS "DETAILS" drone tour (DRONETOUR1..6); rect centres via GraphicWin_local_to_screen(MainWin_g), but steps 1/5 pass raw local left+5 as x (vanilla bug; thunk_tutwin_popx)
extern void TutWin_do_base(struct TutWindow* self, RECT* rc, const char* label, int a4); // addr: 0x004BA870  thinker  thiscall RET 0xC; rect centre -> local_to_screen(BaseWin_g) -> tut_win(MapWin anchor, label, x, y, 0, a4, -1, -1)
extern void TutWin_iface_rect(struct TutWindow* self, RECT* rc, int* x, int* y); // addr: 0x004BC5A0  thinker  thiscall RET 0xC; rect centre -> local_to_screen(0x8A6270)
extern void TutWin_base_rect(struct TutWindow* self, RECT* rc, int* x, int* y);  // addr: 0x004BC5F0  thinker  thiscall RET 0xC; rect centre -> local_to_screen(BaseWin_g)
// field: TutWindow +0x444  struct Buffer canvas   popup canvas (0x8C72AC); TUTOR backdrop draws land here
// field: TutWindow +0x53B4 int tour_running    set 1 by TutWin_tour; cleared by on_button_clicked for ids <= 0
// field: TutWindow +0x53BC int last_button_id  on_button_clicked id (+1 when negative)
// field: TutWindow +0x53C0 int tour_kind       TutWin_tour dispatch key (1 base, 6 drone riots, 7 design)
// field: TutWindow +0x5384 int arrow_to_x     target (map-anchor) screen x; +0x5388 y
// field: TutWindow +0x538C int arrow_from_x   box-attach screen x; +0x5390 y
// field: TutWindow +0x539C int arrow2_from_x  second line attach x (-1 = none); +0x53A0 y; targets +0x5394/+0x5398
// field: TutWindow +0x53A4 int arrow_armed    1 while the pointer line should draw
// field: TutWindow +0x53D4 Win* anchor_win    window the tooltip was raised for (cleared on dismiss)

// ============================================================================
// Load/Save FILE-PICKER (bespoke custom modal; NOT the BasePop pipeline; NATIVE scale)
//   ctor -> FileDlg_layout (all hardcoded geometry, builds a 17-dword rect array)
//   -> FileDlg_build_widgets (copies rects to 0x9b8fd0; clamps SCALE_NUM_G/DEN_G=1:1).
//   The 1:1 clamp is why every element renders native-tiny at hi-res.
// ============================================================================
extern int  load_game(int a1, int a2);                                         // addr: 0x005AAAB0  thinker   cdecl; opens the load-game file picker
extern int  save_game(int mode);                                               // addr: 0x005A9EB0  thinker   cdecl (1 arg); 0 = saved, 1 = cancelled/failed/PBEM; in-game FileDlg, or the Windows dialog when GameHalted / WindowsFileBox
extern int  save_daemon(char* path);                                           // addr: 0x005A94F0  thinker   cdecl; 0 = ok, 1 open fail, 2 header fail, 3 data fail; appends .SAV
extern int  game_data(FILE* fp, int write_file);                               // addr: 0x005A6AC0  thinker   cdecl; save/load body
extern int  load_daemon(char* path, int a2);                                   // addr: 0x005A9760  thinker   cdecl
extern void compute_score(int faction, int* a2, int* a3, int a4);              // addr: 0x005ACBE0  thinker   cdecl
extern int  SecretProjects[64];                                                // addr: 0x009A6514  thinker   base id per project; -1 unbuilt, -2 destroyed
extern int  SaveFileVersion;                                                   // addr: 0x009A6810  thinker   save_daemon stores 12
extern void auto_save(void);                                                   // addr: 0x005ABD20  thinker   cdecl; rotates saves\auto\Alpha Centauri Autosave N.sav (Thinker 5.5 write_jumps here)
extern int  load_game(int a1, int a2);                                         // addr: 0x005AAAB0  thinker   cdecl
extern char* FileDlg_save_modal(struct FileDlg* self);                         // addr: 0x00613D50  observed  fastcall(ecx); returns self+0x208 (path) or 0 when cancelled ([+0x638]==300); restores CWD
extern void FileDlg_ctor(void* self);                                          // addr: 0x00407350  observed  thiscall; GraphicWin+Dialog+ListBox+edit+2 BaseButton ctor
extern void FileDlg_layout(void* self);                                        // addr: 0x00407410  observed  thiscall; hardcoded window/rect geometry; fills 17-dword rect array
extern void FileDlg_show(/*ecx*/ void* self, int a2);                          // addr: 0x00407BE0  observed  thiscall RET 4; FileDlg_vtbl+4; in-game: slide_show then rail_slide_in(self, self+0x3DD8) when the list bar is engaged
extern void FileDlg_hide(/*ecx*/ void* self);                                  // addr: 0x00407C60  observed  thiscall; FileDlg_vtbl+8; in-game: rail_slide_out(self, self+0x3DD8) when engaged, then slide_hide
extern struct ScrollBar* FileDlg_sb_create(/*ecx*/ void* self);                // addr: 0x00407E80  observed  thiscall; FileDlg_vtbl+0x20; ScrollBar_init_inner(0x147,0x15,0x18,0xD8,self,-1,1) at +0x3DD8, hide, rail_slide_in if visible
extern int  FileDlg_sb_remove(/*ecx*/ void* self, void* sb);                   // addr: 0x00407ED0  observed  thiscall RET 4; FileDlg_vtbl+0x24; rail_slide_out if visible; returns 0
// field: FileDlg +0x3280 struct ListBox list      the file list (Dialog part at +[[+0x3280]+8] = +0x3CE0; window part +0x32C8)
// field: FileDlg +0x3704 struct ScrollBar* list_vbar   list window's +0x43C scroll_vert (main menu: heap bar, flags 0x80020; in game: +0x3DD8 via vtbl+0x20)
// field: FileDlg +0x3DD8 struct ScrollBar rail_sb   in-game console-rail list bar (FileDlg_sb_create)
extern void FileDlg_build_widgets(void* dlg, int a1, void* win, int* rects17);  // addr: 0x006139B0  observed  thiscall ecx=Dialog; win=[esp+8], rects17=[esp+c]; copies rects->0x9b8fd0; builds OK/CANCEL/edit/list; dialog renders native 1:1
// 17-dword rect array (FileDlg_layout stack local -> build_widgets arg3); window-LOCAL coords, NATIVE (identical 4K/1600). runtime-confirmed 2026-06-29.
//   [0]=flags  [1..4]=file-list rect  [5..8]=filename-edit rect  [9..12]=OK button  [13..16]=CANCEL button
//   Path A (main-menu LOAD): flags=0x80060 list{14,42,319,330} edit{17,332,317,352} OK{19,358,165,380} CANCEL{168,358,315,380}
//   Path B (in-game SAVE):   flags=0       list{28,32,333,320} edit{31,322,331,342} OK{33,348,179,370} CANCEL{182,348,329,370}
//   element SIZES identical across paths (list 305x288, edit 300x20, OK 146x22, CANCEL 147x22); paths differ only in offset
extern void FileDlg_load_title(void* self);                                    // addr: 0x00407A80  observed  load title bar; find_font(0xE,1,..) 14px caption
extern void FileDlg_save_title(void* self);                                    // addr: 0x00407920  observed  save title bar
extern int  FileDlg_load_modal(void* self);                                    // addr: 0x00613F60  observed  load modal loop; GetCurrentDirectory+FindFirstFile populate
extern int  FileDlg_save_modal(void* self);                                    // addr: 0x00613D50  observed  save modal loop
// field: FileDlg +0x638 int   result_code        300 = cancelled
// field: FileDlg +0x63c Dialog* dialog            list/edit dialog object
// field: FileDlg +0x660 BaseButton OK
// field: FileDlg +0x11ac BaseButton CANCEL
extern void FileDlg_draw_row(int sprites, int type, int a3, int x, int y, int rowH);  // addr: 0x004072D0  observed  FileDlg +0x32b0 per-row draw callback: Buffer_tile bg + FileDlg_draw_row_icon
extern void FileDlg_draw_row_icon(int sprites, int type, int a3, int x, int y, int rowH);  // addr: 0x00614C50  observed  FileDlg +0x289c row icon callback; 3 Sprite_draw_2(...,num=1,den=1) for file/drive/folder icons (16x16 from jackal.pcx)
extern int  FileDlg_bg_fill(void* self);                                       // addr: 0x0042A100  observed  ListBox-class vtable method (slot 0x66afac; ctors 0x429147/0x4322b5) RET 4; tiles unselected navy dither (0x78d548) over rect [self+0x474]. NOTE: does NOT fire for the LOAD/SAVE dialog (traced) — that list background is drawn by Buffer_copy_4 @0x60bbba/0x60c421 instead
extern void* g_filedlg_rowtile_sel;                                            // addr: 0x0078D9D0  observed  DAT_0078d9d0: FileDlg SELECTED-row bg tile (24x24, blue 1px horizontal scanline dither idx 224/225)
extern void* g_filedlg_rowtile_unsel;                                          // addr: 0x0078D548  observed  DAT_0078d548: FileDlg UNSELECTED-row bg tile (24x24, navy 1px horizontal scanline dither idx 65/196)
extern void ListBox_draw_item(/*ecx*/ void* self, int item_idx);               // addr: 0x0060B530  observed  thiscall; generic list-row renderer. row rowH = Dialog[+0x68](line-height), pitch = [+0x68]+[+0x44](gap); Dialog sub-object at self + adjustor [[ecx]+8] (0xA60 for FileDlg)
// field: Dialog +0x34 int   text_indent         row text x-advance past the icon (native; scaled x g/16 for FileDlg)
// field: Dialog +0x48 int   row_stride          rowH+gap; -1 = derive from font; FileDlg native 22, single store @0x40777A in FileDlg_layout; type-2 popup (#SELECTSERVICE) native 19
// field: Dialog +0x60 int   area_height         list-area h fed to ListBox_attach's GraphicWin_init; derived rows x (+0x68) + gaps, or explicit +0x30 when flag [+0x20]&1 and +0x30 != 0
// field: Dialog +0x68 int   line_height         row height; DERIVED by ListBox_calculate_dimensions = (+0x48)-(+0x44) (or font height+gap-gap when +0x48==-1), RE-DERIVED on every list populate
extern void ListBox_calculate_dimensions(/*ecx*/ void* self);                  // addr: 0x0060A1E0  observed  thiscall; derives Dialog line_height/visible-rows/paging from row_stride & row_gap; runs on attach AND update_changes (every populate)
// field: Popup +0x2D70 struct Dialog listbox_dialog   ListBox (popup+0x2218) Dialog fields via the vbtable adjust: +0x2c min_w = #xs (popup+0x2D9C), +0x34 (+0x2DA4), +0x44 gap (+0x2DB4), +0x48 stride (+0x2DB8), +0x54 cols (+0x2DC4), +0x58 visible (+0x2DC8), +0x5c w5c dialog width (+0x2DCC, == BasePop's [iv3+0x222c] term), +0x60 h (+0x2DD0), +0x64 row bar width (+0x2DD4), +0x68 row h (+0x2DD8)
// ListBox_calculate_dimensions bar-reserve sites: `mov ecx,[g_scrollbar_w]` @0x60A632 -> [+0x5c] += @0x60A63D (single column, rows overflow, win flag clear); twin @0x60A609 -> [+0x60] += @0x60A614 (multi-column); `mov eax,[g_scrollbar_w]` @0x60A650 -> [+0x64] -= eax/[+0x54] @0x60A659 (dialog flag&2)
extern void ListBox_attach(/*ecx*/ void* self);                                // addr: 0x0060A670  observed  thiscall; (re)binds the list child window + calc_dims
extern void FileDlg_populate_list(/*ecx*/ void* self, char* dir);              // addr: 0x00614360  observed  thiscall; SetCurrentDirectoryA + item-list clear + DlgDirListA + ListBox_item loop + attach/update_changes; runs on OPEN and on EVERY directory navigation
extern void FileDlg_activate_entry(/*ecx*/ void* self);                        // addr: 0x006146A0  observed  thiscall; activates the selected/typed entry; directory (or "..") -> FileDlg_populate_list
extern int  FileDlg_on_nav(/*ecx*/ void* self, int cmd);                       // addr: 0x00614B90  observed  thiscall; FileDlg command handler (vtable +0xB0 via stub 0x407CD0): cmd 3 = up-directory (chdir ".." + populate), -1 = activate entry, -2 = cancel
extern void FileDlg_set_filename(/*ecx*/ void* self, char* name);              // addr: 0x006141C0  observed  thiscall; copies the picked name into the edit field

// ============================================================================
// "CHOOSE YOUR FACTIONS" picker window (bespoke GraphicWin, NATIVE 790x300 @ (5,5), NO g/16 scaling)
//   runtime-confirmed 2026-06-21 (frida_faction_unified); levers in work\faction_levers_CONFIRMED.md.
//   NB: FUN_00429300 is NOT this window -- it is the Datalinks/encyclopedia window.
// ============================================================================
extern struct PickWindow* PickWin;                                             // addr: 0x00822718  thinker   static faction picker window object
extern void FactionPickWin_build(int self);                                    // addr: 0x004887A0  observed  thiscall this=ECX; GraphicWin_init(5,5,790,300); reads ALPHAX FACTIONS/NEWFACTIONS/CUSTOMFACTIONS + pickfac.pcx; builds all child buttons
extern void FactionPickWin_redraw(int self);                                   // addr: 0x00489660  observed  fastcall this=ECX; #1 frame d690@+0x623c/d5a0+d618@+0x624c, #2 title Buffer_write_cent_l_7(Strings 0x1168), #6 list, #7 selection arrow (color 0xe0, mode +0x12640)
extern int  FactionPickWin_exec(int* self);                                    // addr: 0x0048A810  observed  fastcall; runs the modal, returns selected faction id (self[0x176a])
// field: FactionPickWin +0x623c RECT frame_outer        {0,0,790,300} d690 backdrop
// field: FactionPickWin +0x624c RECT title_frame         {4,4,786,34} d5a0/d618 title bar
// field: FactionPickWin +0x6244 int  win_w               =790
// field: FactionPickWin +0x6248 int  win_h               =300
// field: FactionPickWin +0x625c RECT portrait_prev_0     {5,38,263,128}  (id 0x100)
// field: FactionPickWin +0x626c RECT portrait_prev_1     {265,38,523,128} (id 0x101)
// field: FactionPickWin +0x627c RECT portrait_prev_2     {525,38,783,128} (id 0x102)
// field: FactionPickWin +0x86ac RECT namelist_rect       {336,134,762,264} Dialog_init_3; row pitch 0x13=19
// field: FactionPickWin +0x86bc struct ListBox namelist     faction-name ListBox; GraphicWin part +0x48, Dialog part +0xA60
extern void* FactionPickWin_vtbl;               // addr: 0x0066D13C  observed  +0x2C = FactionPickWin_row_painter (ListBox_draw_item's row background callback)
extern int  FactionPickWin_row_painter(void* win, int id, int state, RECT* r); // addr: 0x0048A840  observed  thiscall RET 0x10; row box set 0x78D960 + state*0x28
// field: FactionPickWin +0x9240 RECT btn_play_selected   {6,132,222,154} (id 0x104); also #7 arrow anchor
// field: FactionPickWin +0x9250 RECT btn_play_random     {6,157,222,179} (id 0x105)
// field: FactionPickWin +0x9210 RECT btn_change_name      {199,271,391,293} (id 0x106)
// field: FactionPickWin +0x9220 RECT btn_info             {5,271,197,293} (id 0x107)
// field: FactionPickWin +0x9230 RECT btn_cancel           {587,271,779,293} (id 0x103)
// field: FactionPickWin +0x9260 RECT btn_ok               {393,271,585,293} (id 0x108)
// field: FactionPickWin +0xd638 RECT[7] row_select_btns   16x16 @ x=764, pitch 19 (ids 0x3039..0x303f)
// field: FactionPickWin +0x12640 int  sel_mode            0x104=single-select / 0x105=multi-row
// field: FactionPickWin +0x8688 byte blit_key            =9

// ============================================================================
// DIPLOMACY talk screen ("DiploTalkWin" @0x733990: 700x450 GraphicWin over the
//   HUD strip + iface-mode subobject that re-skins MainWin's canvas; the speech
//   box is the ordinary script Popup with external window = DiploTalkWin.
//   Thinker's DiploWin 0x73ACD8 is the MULTIPLAYER negotiation window.)
// ============================================================================
extern struct GraphicWin DiploTalkWin;                       // addr: 0x00733990  observed  static; size 0x433C; vtbl 0x66B478 (canvas Flic vtbl 0x66B470, iface vtbl 0x66B424 at +0xA14)
extern void DiploTalkWin_ctor(struct GraphicWin* self);      // addr: 0x0043EFF0  observed  thiscall; static-init thunk @0x43EFC0
extern void DiploTalkWin_init(struct GraphicWin* self);      // addr: 0x00440700  observed  thiscall; desktop_init @0x58EEC1; GraphicWin_init(0,0,700,450 [600-strip @800],parent MapWin) @0x440AFD; Win_move((SW-700+0x20)/2, SH-strip-450) @0x440B3B; frame d690 (L+0x17,T,R-0x37,B) @0x440B8B; 3 BaseButton_init parent MainWin_g
extern void DiploTalkWin_dtor(struct GraphicWin* self);      // addr: 0x00440D50  observed  thiscall; scalar dtor 0x440EC0 = vtbl+0
extern void DiploTalkWin_show(struct GraphicWin* self);      // addr: 0x0043F140  observed  thiscall; vtbl+4; Win_show(0) iff [+0xA94]!=-1
extern void DiploTalkWin_hide(struct GraphicWin* self);      // addr: 0x0043F170  observed  thiscall; vtbl+8
extern void DiploTalkWin_open(struct GraphicWin* self, int faction); // addr: 0x0043F2B0  observed  thiscall RET 4; caller wants_to_speak @0x53E239; BasePop_set_def_external_window(this,0,0,700,450) + iface mode + Flic_init dip_?_n.flc (0x16+4,0x50+10) & <faction>.flc
extern void DiploTalkWin_close(struct GraphicWin* self);     // addr: 0x0043F5C0  observed  thiscall; diplomacy_ends @0x53E48E; release_iface_mode + Flic_dtor x2 + [+0xA94]=-1
// field: DiploTalkWin +0xA94 int32 talk_faction    ; faction spoken to (open @0x43F30D), -1 idle (close @0x43F5E4); NOT a per-popup anchored key
extern void DiploTalkWin_draw_strip(struct GraphicWin* self); // addr: 0x004402A0  observed  thiscall; vtbl+0x30; tile_panels(1) + frames d5a0/d870 + the 4 panel painters, all onto MainWin canvas 0x7AEC64
extern void DiploTalkWin_draw_bioscan_panel(struct GraphicWin* self); // addr: 0x0043F5F0  observed  thiscall; BIOSCAN header d618 [+0x20C4] + body d528 [+0x20D4] + colour bar Sprite_draw_2 @0x43F778
extern void DiploTalkWin_draw_news_panel(struct GraphicWin* self);    // addr: 0x0043F790  observed  thiscall; [+0x20E4] d528 + hline @0x43F818 + name/REPUTATION/MOOD text
extern void DiploTalkWin_draw_status_panels(struct GraphicWin* self); // addr: 0x0043FA90  observed  thiscall; two half panels of [+0x20F4] (split @0x43FAC3); logo + name + DIPLOMATIC STATUS/INFILTRATION/Energy/Might; also called by diplomacy_caption @0x539B53
extern void DiploTalkWin_draw_hq_panel(struct GraphicWin* self);      // addr: 0x00440080  observed  thiscall; [+0x2114] d528 + HQ name + base pic; blank tile when [+0x4208]==0
extern void DiploTalkIface_on_mode(struct SubInterface* self, int enter); // addr: 0x00440380  observed  thiscall RET 4; iface vtbl 0x66B424+0; enter: draw_strip + slide_show(win,2) + timers + globe buttons
extern void DiploTalkIface_on_button_clicked(struct SubInterface* self, int id); // addr: 0x00440550  observed  thiscall RET 4; iface vtbl+0x34; 0 DATALINKS->DatalinkWin 0x429180(0xF,f) 1 PROFILE->report_intel 2 HQINFO->DetailWin toggle
extern void DiploTalkIface_on_event(struct SubInterface* self, int type, int a2, int id); // addr: 0x00440620  observed  thiscall RET 0xC; iface vtbl+0x40; ids 6/7 = globe buttons 0x3EE/0x3EF
extern void DiploTalkWin_on_command_forward(struct GraphicWin* self); // addr: 0x0043F290  observed  thiscall; vtbl+0xB0; forwards to [g_current_basepop] vtbl+0xB0
extern void DiploTalkWin_set_modal(struct GraphicWin* self, int flags, int a2); // addr: 0x004406D0  observed  thiscall; vtbl+0xE4; Win_set_modal(flags|1,a2,&MainWin_g)
extern void DiploTalkWin_bioscan_tick(int unused, struct GraphicWin* self); // addr: 0x0043F200  observed  cdecl Time cb (+0xA98); Flic_draw_frame(+0x15CC) + soft_update(+0x1B58)
extern void DiploTalkWin_news_tick(int unused, struct GraphicWin* self);    // addr: 0x0043F250  observed  cdecl Time cb (+0xAC0, 2000ms); Flic_draw_frame(+0xAE8) + soft_update(+0x1074)
extern void Popup_on_adjust_button_placement(struct BasePop* self, int a2, int* y); // addr: 0x00405050  observed  thiscall RET 0xC; anchored ([+0xA14]!=0) arm writes *y=-0x1e @0x40507F, else *y+=3
extern void BasePop_on_adjust_button_placement(struct BasePop* self, int a2, int* y); // addr: 0x00406B20  observed  thiscall RET 0xC; BasePop vtbl+0x178, no-op
extern int  g_console_big_center;                             // addr: 0x007D3930  observed  = MainWin+0x25110; 1 while slide_show(win,2) is up (tile_panels tiles DD0/DC0 instead of DB0/DA0); cleared by slide_hide
extern struct Sprite g_diplo_bezel_sprite;                    // addr: 0x007D177C  observed  centre-console bezel art drawn by slide_show diplo tail @0x45D8E9 at (MainWin+0xD3C,+0xD40)
// field: MainWin +0xD3C int bezelX      slide_show diplo bezel sprite x (seed-scaled); +0xD40 y
// field: MainWin +0xDD0 RECT rcConsoleBottomBig  DB0 twin used by tile_panels when g_console_big_center (written @0x459A8C)
// field: DiploTalkWin +0x20B4 struct Sprite* newsSepSprite  164x198 interface.pcx piece; only its height sets the news-panel separator y
// field: DiploTalkWin +0x2158 struct FlatButton btnDatalinks   id 0 (=0x735AE8); +0x2CA4 btnProfile id 1 (=0x736634); +0x37F0 btnHqinfo id 2 (=0x737180); stride 0xB4C
extern struct DiploWindow DiploWin;                                              // addr: 0x0073ACD8  thinker   multiplayer negotiation window; GraphicWin 832 x (0x254-strip), parent MapWin
extern void DiploWin_ctor(struct DiploWindow* self);                             // addr: 0x00444FC0  observed  thiscall; vtbls 0x66B634 / 0x66B62C / iface 0x66B5E0 at +0xA14
extern void DiploWin_build(struct DiploWindow* self, int, int);                  // addr: 0x00443F10  observed  thiscall; GraphicWin_init @0x444617 (w literal 0x340); via wrapper 0x444D90
extern void diplo(int, int);                                                     // addr: 0x00444D90  thinker   cdecl; multiplayer negotiation entry; calls DiploWin_build
extern void DiploWinIface_on_mode(struct SubInterface* self, int enter);         // addr: 0x00443C70  observed  thiscall RET 4; slide_show(win,2) @0x443CBC / slide_hide(win,2) @0x443D47
extern void* DiploWin_vtbl[];                                                     // addr: 0x0066B634  observed  main vtbl: +0x30 DiploWin_draw, +0x4C DiploWin_on_lclick, +0x64 DiploWin_on_key, +0xB0 DiploWin_on_command, +0xE4 set_modal
extern void* DiploWinIface_vtbl[];                                                // addr: 0x0066B5E0  observed  iface vtbl at +0xA14 (mode 0xB): slot 0 DiploWinIface_on_mode
extern int  DiploWinIface_item_back(struct GraphicWin* win, int a2, int state, RECT* rect); // addr: 0x00443E50  observed  RET 0x10, ecx unused; iface vtbl+0x48; state 0 GraphicWin_fill_2, else Buffer_box_sprite(0x78D960 + state*0x28) @0x443EEF
extern void DiploWin_draw(struct DiploWindow* self);                              // addr: 0x004436C0  observed  thiscall; console frames, rings, TRADE/DIPLOMACY/status captions, then the side + offers painters
extern void DiploWin_draw_left(struct DiploWindow* self);                         // addr: 0x00442A10  observed  thiscall; faction 1 name box, panel, art, status box
extern void DiploWin_draw_right(struct DiploWindow* self);                        // addr: 0x00442DC0  observed  thiscall; faction 2 name box, panel, art, status box
extern void DiploWin_draw_offers(struct DiploWindow* self);                       // addr: 0x00443170  observed  thiscall; both offer lists + their Spot_add hit rows
extern void DiploWin_on_lclick(struct DiploWindow* self, int x, int y);           // addr: 0x00442510  observed  thiscall; Spot_check on the offer rows
extern void DiploWin_on_key(struct DiploWindow* self, int key);                   // addr: 0x00442590  observed  thiscall; ESC releases the modal, Enter sends the chat line
extern void DiploWin_on_command(struct DiploWindow* self, int id);                // addr: 0x004415C0  observed  thiscall; button ids 2..12, -2/4 release the modal
extern void Buffer_map_colors_2(struct Buffer* self, RECT* rect, const void* lut); // addr: 0x005DA4D0  thinker   thiscall; palette LUT remap over a rect
// field: DiploWin +0xAB4 int faction1        the local side (diplo arg 1)
// field: DiploWin +0xAB8 int faction2        the counterparty (diplo arg 2)
// field: DiploWin +0xED0 Spot spots          offer-row hit list (Spot_init 100)
// field: DiploWin +0xEDC RECT frame          d690 backdrop / window frame
// field: DiploWin +0xF2C RECT edit_rect      chat edit line (MainWin coords, seed DC0)
// field: DiploWin +0xF3C RECT chat_rect      chat log (MainWin coords, seed DC0)
// field: DiploWin +0xF4C RECT header         Communications Link caption box
// field: DiploWin +0xF5C RECT panel_left     faction 1 panel; +0xF6C panel_right
// field: DiploWin +0xF7C RECT name_left      faction 1 name box; +0xF8C name_right
// field: DiploWin +0xF9C RECT trade_hdr      TRADE header; +0xFAC trade_ring; +0xFBC diplo_hdr; +0xFCC diplo_ring
// field: DiploWin +0xFDC RECT btn_rects[13]  button rects by id (stride 0x10; ids 2..12 have widgets)
// field: DiploWin +0x10AC FlatButton buttons[13] by id (stride 0xB4C; ids 0/1 unused)
// field: DiploWin +0xA388 TextScroll chat_log parent MainWin; its ScrollBar at +0xA20
// field: DiploWin +0xDA7C EditLine chat_edit parent MainWin
extern void BasePop_set_def_external_window(struct GraphicWin* win, int x, int y, int w, int h); // addr: 0x006050F0  thinker  cdecl; writes g_popup_def_ext_win/x/y/w/h
extern struct GraphicWin* g_popup_def_ext_win;              // addr: 0x009B8D04  observed  default external window copied into BasePop+0xA14 by BasePop_ctor @0x600DFF / BasePop_close @0x6014B8; only writer 0x6050F0 (never cleared)
extern int  g_popup_def_ext_x;                              // addr: 0x009B8D08  observed  -> BasePop+0xA18
extern int  g_popup_def_ext_y;                              // addr: 0x009B8D0C  observed  -> BasePop+0xA1C
extern int  g_popup_def_ext_w;                              // addr: 0x00696EC4  observed  -> BasePop+0xA20 (Dialog +0x21FC seed)
extern int  g_popup_def_ext_h;                              // addr: 0x00696EC8  observed  -> BasePop+0xA24 (Dialog +0x2200 seed)
extern struct BasePop* g_current_basepop;                   // addr: 0x009B8D7C  observed  BasePop being exec'd (BasePop_exec_3 writes @0x6036CE/0x60371E)
extern struct SubInterface* g_iface_diplo_talk;             // addr: 0x007AE800  observed  = DiploTalkWin+0xA14 (mode id 4); MP twin 0x7AE81C = DiploWin+0xA14 (mode 0xB)
extern struct Sprite* g_faction_portrait_table[8];          // addr: 0x006846D8  observed  = 0x78EE48+f*0x65C (131x157 leader portrait, interface.pcx (0x130,0x1C9)); X_pops art for diplomacy popups
extern BYTE g_faction_sprites[8][0x65C];                    // addr: 0x0078E978  observed  per faction: 37 Sprites (0x2C each) from +0; filled by load_faction_art
extern struct Sprite* g_base_sprite_table[];               // addr: 0x0076E590  observed  base_draw's Sprite* per base icon (into g_faction_sprites)
extern struct Sprite g_faction_council_small[8];            // addr: 0x0078EDF0  observed  stride 0x65C; 96x115 council/combat portrait, unframed
extern struct Sprite g_faction_council_big[8];              // addr: 0x0078EE1C  observed  stride 0x65C; 118x144 leader portrait, unframed
extern struct Sprite g_faction_art[8];                      // addr: 0x0078EE48  observed  stride 0x65C: +0 portrait 131x157, +0x2C logo 65x50, +0x58 base pic 233x124, +0x84 164x198; filled by load_faction_art
extern struct Sprite g_diplo_colour_bar_sprite;             // addr: 0x007D161C  observed  = MainWin+0x22DFC; BIOSCAN colour bar (9x147, 1-row scanline gradient) drawn by DiploTalkWin_draw_bioscan_panel with the sprite's own key byte (+8)
// field: DiploTalkWin +0xA14 struct SubInterface iface   vptr 0x66B424; +0xA18 mode id 4; +0x80 (=+0xA94) faction
// field: DiploTalkWin +0xA1C struct Font font10        Font_init(g_hud_font_name,10,0) @0x440A57
// field: DiploTalkWin +0xA44 struct Font font12        (12,0) [10 @800] @0x440A6D
// field: DiploTalkWin +0xA6C struct Font font14b       (14,1) [12,1 @800] @0x440A7E; buttons + panel headers
// field: DiploTalkWin +0xA94 int faction              talked-to faction, -1 idle
// field: DiploTalkWin +0xA98 struct Time timer_bioscan  cb 0x43F200, period = flic delay [+0x1FF0]
// field: DiploTalkWin +0xAC0 struct Time timer_news     cb 0x43F250, 2000ms
// field: DiploTalkWin +0xAE8 struct Flic flic_news      <faction>.flc / faction.flc at ([+0x20E4].L+1, T+1+H/4); rect +0x1074, frame args +0x1094/+0x1098; dst = MainWin strip buffer 0x7AEC64; runs DIRECT (flags 0x1)
// field: DiploTalkWin +0x15CC struct Flic flic_bioscan  dip_{a,f,m}_{0..2}.flc at (26,90) [800: (22,80)]; rect +0x1B58, frame args +0x1B78/+0x1B7C, delay +0x1FF0; dst = MainWin strip buffer 0x7AEC64; runs KEYED (flags 0x3, key 9)
// field: DiploTalkWin +0x20B0 int frame_counter
// field: DiploTalkWin +0x20B4 struct Sprite* news_height_src   = g_faction_art[f]+0x84 (h sets the news-panel separator y)
// field: DiploTalkWin +0x20B8 struct Sprite* colour_bar        = 0x7D161C
// field: DiploTalkWin +0x20BC struct Sprite* logo              = g_faction_art[f]+0x2C
// field: DiploTalkWin +0x20C0 struct Sprite* base_pic          = g_faction_art[f]+0x58
// field: DiploTalkWin +0x20C4 RECT rcBioscanHdr   (8,60,236-flcW,80) native
// field: DiploTalkWin +0x20D4 RECT rcBioscanBody  (8,82,236-flcW,248)
// field: DiploTalkWin +0x20E4 RECT rcNews         (239-flcW,60,241,248); flcW = max(40, faction.flc frame width)
// field: DiploTalkWin +0x20F4 RECT rcCenter       (269,73,756,204) = MainWin+0xDC0 inset 7, B-0x17; alias 0x735A84
// field: DiploTalkWin +0x2104 RECT rcUnused       MainWin+0xDB0 inset 4 (never read)
// field: DiploTalkWin +0x2114 RECT rcHqPic        (783,60,1016,208)
// field: DiploTalkWin +0x2124 RECT rcBtnDatalinks (269,207,511,227)
// field: DiploTalkWin +0x2134 RECT rcBtnProfile   (514,207,756,227)
// field: DiploTalkWin +0x2144 RECT rcBtnHqinfo    (785,214,901,246)
// field: DiploTalkWin +0x2154 int one
// field: DiploTalkWin +0x2158 struct FlatButton buttons[3]   stride 0xB4C; ids 0 DATALINKS / 1 Profile / 2 HQINFO; parent MainWin_g; [2]+0xA18 (=+0x4208) gates the HQ picture
// field: BasePop +0xA14 struct GraphicWin* ext_win   external window (popup becomes its child at +0xA18/+0xA1C, size +0xA20/+0xA24); 0x733990 while diplomacy talk is visible
// field: BasePop +0xA18 int ext_x
// field: BasePop +0xA1C int ext_y
// field: BasePop +0xA20 int ext_w
// field: BasePop +0xA24 int ext_h

// ============================================================================
// SCENARIO-EDITOR DIPLOMACY editor (bespoke GraphicWin modal, NATIVE 758x398,
//   NO g/16 scaling; only its CheckList child inherits the popup_list_* patches)
// ============================================================================
extern void Console_editor_diplomacy(struct Console* self);       // addr: 0x004DB870  thinker  thiscall; EDITORWHO faction picker then DiploEditWin_exec
extern void DiploEditWin_exec(void* self, int faction);           // addr: 0x004DB080  observed  thiscall RET 4; builds+runs the 758x398 diplomacy modal; sole consumer = E8 @0x4DBB19 (whole-file census: NO vtable ref; 0x66E964 holds 0x4E23C0)
extern void DiploEditWin_update(void* self);                      // addr: 0x004DADA0  observed  thiscall; pre-show populate
extern void DiploEditWin_loop(void* self);                        // addr: 0x004DA990  observed  thiscall; modal event loop
extern void DiploEditWin_dtor(void* self);                        // addr: 0x004E2240  observed  thiscall; accept-path call @0x4DBB2B
extern void* g_diploeditwin_vtbl;                                // addr: 0x0066E964  observed  DiploEditWin vtable
extern int PopupDialogState;                                      // addr: 0x006A721C  thinker  popup/list layout state (0 modal, 6 list family, 1-5 others); exec's call tree leaves 6 armed (vanilla leak)
extern void* CheckList_ctor(void* self, int alloc);               // addr: 0x0060E670  observed  thiscall RET 4; checkbox-list widget: GraphicWin@+0x1c, Dialog@+0xa34, vtbl 0x670718
extern void CheckList_init(void* self);                           // addr: 0x0060E7C0  observed  thiscall; row-measure call @0x60E835
extern void CheckList_add_item(void* self, const char* label, int mask, int a3); // addr: 0x0060E980  observed  thiscall
// field: CheckList +0x10 struct Sprite* sprite_a   checkbox sprite (ctor default [0x697104])
// field: CheckList +0x14 struct Sprite* sprite_b   checkbox sprite (ctor default [0x697108])
// field: CheckList +0x1C struct GraphicWin win      vtbl 0x670718 [+4] adjustor; +0x970 label font (its descent seeds the row label rect top)
// field: CheckList +0xA34 struct Dialog dlg         vtbl [+8] adjustor; +0x34 indent, +0x44 gap, +0x48 row_h preset, +0x68 row_h
// field: PrefWin +0x5974 struct CheckList lists[7]  stride 0xB28 (0x5974,0x649C,0x6FC4,0x7AEC,0x8614,0x913C,0x9C64; tab order)
extern void CheckList_draw_item(/*ecx*/ void* self, int idx, int flag);   // addr: 0x0060F030  observed  thiscall RET 8; row painter: rowTop=listY+gap/2+i*(rowH+gap); box Sprite_draw_2 y=rowTop+((max(rowH,lineH)-sprH)>>1) (sites 0x60F41C/0x60F457 -> thunk_checkbox_scale); label Buffer_write_l_4 rect (rowTop+win.font.descent .. rowTop+max(rowH,lineH)), x=rowX+indent (0x60F47E)
extern void CheckList_on_click(/*ecx*/ void* win, int x, int y);       // addr: 0x0060F700  observed  thiscall RET 8; this = CheckList+0x1C; row = y/(rowH+gap) @0x60F735, col = x/(+0x64 + gap); toggles the row bit of Dialog +0xEC
// field: Dialog +0xEC int check_bits      type-1 checkbox state bitmask (bit per row)
// field: Dialog +0xF0 int hover_row       the list's hover row; CheckList_draw_item draws it in back state 1 (unless checked: 2)
extern int  OptionList_calc_reserve(/*ecx*/ void* self);                   // addr: 0x0060ED10  observed  fastcall; list dims: [+0x34]=max sprite w if 0; [+0x68]=max([+0x48] (-1 -> max sprite h), Buffer_text_height); [+0x64]=gap+indent+max text w; [+0x60]=([+0x68]+[+0x44])*[+0x58]
// field: DiploEditWin +0xa14 int width    dup of GraphicWin_init w arg (0x2F6)
// field: DiploEditWin +0xa18 int height   dup of GraphicWin_init h arg (0x18E)
// field: DiploEditWin +0xa1c int faction_id
// field: DiploEditWin +0xa20 int sel_faction
// field: DiploEditWin +0xa24 struct Font font14        dialog font, Font_init 14pt @0x4DB09B
// field: DiploEditWin +0xa4c struct ListBox faction_list   left panel, ListBox_ctor 0x609DB0
// field: DiploEditWin +0x15a0 struct CheckList treaty_list  right panel, 13 DIPLO_ bitmask items

// ============================================================================
// MULTIPLAYER SETUP lobby ("NetWin", bespoke static GraphicWin @0x80A6F8;
//   built at hard-coded 800x600 + Win_center, NO g/16 scaling)
// ============================================================================
extern struct GraphicWin NetWin;                                               // addr: 0x0080A6F8  thinker   static lobby window object (>=0x7734 bytes); vtable 0x0066CCEC
extern void NetWin_ctor(void* self);                                           // addr: 0x00481C50  observed  thiscall; static-init stub 0x47AFF0; subobjects: chat TextScroll, EditLine, Strings, 2x FlatButton
extern int  NetWin_setup_lobby(void* self);                                    // addr: 0x00482490  observed  thiscall; builds window (GraphicWin_init(0,0,800,600) @0x482604 <- PUSH 0x320/0x258 @0x4825FB/0x4825F6, Win_center @0x48260B), fills rect table, runs modal; sole caller multiplayer_init @0x58DBDA
extern void NetWin_draw(void* self);                                           // addr: 0x00481AD0  observed  vtable+0x30 content draw; also called by NetDaemon roster refresh @0x52E32F/0x52E8A6/0x537CB9/0x537EB5/0x537F2B
extern void NetWin_draw_settings(void* self);                                  // addr: 0x00480900  observed  left settings panel; row pitch = Buffer_text_line_height; arrow sprite [0x788040] x8
extern void NetWin_draw_players(void* self);                                   // addr: 0x00480370  observed  players header + roster rows; lock frames 0x78DCA8/0x78DCF8; toggle sprites [0x7AC048]/[0x7AC074] native 1:1
extern void NetWin_draw_factions(void* self);                                  // addr: 0x0047FED0  observed  faction column rows ("Random")
extern void NetWin_draw_handicaps(void* self);                                 // addr: 0x00480180  observed  handicap column rows ("Talent"); strings 0x96C85C
extern void NetWin_draw_options(void* self);                                   // addr: 0x0047F960  observed  CUSTOM GAME OPTIONS; body font find_font(0xC,1) @0x47FA6E; row step 0x14 @0x47FBA6/0x47FDF1, indent 0x19 @0x47FB0B/0x47FD67/0x47FDAA, col2 L+=R+=0x18A @0x47FDBB, y-=0xA0 @0x47FDC9 after item 7; checkbox core CALLs @0x47FAD4/0x47FD2B sprites 0x7794D8+idx*0x2C
extern void NetWin_modal_proc(void);                                           // addr: 0x00483240  observed  modal idle proc; pumps NetDaemon 0x530320 + redraws via [vtbl+0x30] @0x483274
extern int  NetWin_on_command(void* self, int id);                             // addr: 0x0047B450  observed  vtable+0xB0 command handler; Net_send/X_pop_2
extern int  NetWin_player_color(int player);                                   // addr: 0x0047B380  observed  per-player text color (cb stored at NetWin+0x1190)
extern int  NetWin_on_click();                                                // addr: 0x0047B760  observed  thiscall; vtable+0x4C; Spot_check on NetWin+0xD34 then switch on spot type
extern int  NetWin_pick_faction(void* self, int slot);                         // addr: 0x0047C530  observed  thiscall; faction-column menu; writes the slot's faction pick, then NetWin_faction_password(1)
extern int  NetWin_faction_password(void* self, int verify);                   // addr: 0x0047C970  observed  thiscall RET 4; ENTERPASSWORDNEW / ENTERPASSWORDFACTION / VERIFYPASSWORD prompts; padlock spot calls it with 0
extern char g_mp_slots[];                                                      // addr: 0x0090DB98  observed  lobby player records, stride 0x17C
// field: g_mp_slots +0x3   char  faction_pick   -1 = Random
// field: g_mp_slots +0x178 int   faction_password   0 = none
extern void mp_defaults_init(void* self);                                      // addr: 0x00481E90  observed  thiscall; pure MP-defaults data init (Thinker write_byte 0x481EE0/E7/EE/F5); caller multiplayer_init @0x58DB57
extern int  multiplayer_init(void);                                            // addr: 0x0058DB30  thinker   callers: top_menu @0x58E904, control_game @0x52AC68; calls NetWin_setup_lobby @0x58DBDA; lobby retcheck cmp eax,esi(=1)/jl @0x58DBDF
extern int  top_menu(int a1);                                                  // addr: 0x0058E360  thinker   builds/reuses TopMenuWin (GraphicWin_ctor+GraphicWin_init(0,0,ScreenW,ScreenH)) + picks [x]opening[a|b].pcx by ScreenW==800 / SMACX flag [0x9A6488]
extern int  change_opening(char* pcx_name);                                    // addr: 0x00589A30  thinker   cdecl; Buffer_load_pcx to local, then Buffer_copy_3 stretch to TopMenuWin FULL W*H @0x589AE8 (anamorphic at wide res; accepted as-is 2026-07-04)
extern void close_opening(void);                                               // addr: 0x00589B20  thinker   5 callers
extern struct GraphicWin* TopMenuWin;                                          // addr: 0x00945824  thinker   full-screen opening backdrop window, ScreenW x ScreenH (top_menu creates, change_opening fills, SetupWin decorations draw into +0x444, loading screens reuse)
extern int  ExpansionEnabled;                                                  // addr: 0x009A6488  thinker   SMACX expansion flag; top_menu picks xopening*.pcx when set
extern int  init_opening(const char* pcx_name);                                // addr: 0x00589B60  thinker   no direct E8 callers
extern void TextScroll_ctor(void* self);                                       // addr: 0x00629110  observed  scroll-text widget ctor (chat log; 9 caller screens incl Datalinks 0x429300)
extern int  TextScroll_attach(void* self, ...);                                // addr: 0x006292D0  observed  thiscall; creates child GraphicWin from rect args; scrollbar w from g_scrollbar_w; SHARED (9 callers) - scale ARGS at call site only
extern void ScrollBar_subctor(void* self);                                     // addr: 0x00605370  observed  thiscall; inits scrollbar fields +0xA14..+0xAA4 from config globals 0x9B8DE0.. + sprite ptrs
extern int  ScrollBar_attach(void* self, ...);                                 // addr: 0x00605890  observed  thiscall; bar width from g_scrollbar_w (read @0x6058AE, pushed @0x6058B3); inner attach 0x6054D0
extern int  ScrollBar_attach_rect(void* self, RECT* r, void* parent, int id, int flags); // addr: 0x00605840  observed  thiscall RET 0x10; pure rect form -> ScrollBar_init_inner(x,y,w,h,...) - NO g_scrollbar_w read; arrow buttons sized w x w from the rect, track = h-2w
// field: ScrollBar +0xAAC FlatButton sb_btn_up      label-less arrow (stride 0xB4C -> +0x15F8; ScrollBar obj size 0x214C)
// field: ScrollBar +0x15F8 FlatButton sb_btn_down   label-less arrow
extern void ScrollBar_draw(void* self);                                        // addr: 0x006066F0  observed  thiscall; draws arrow buttons (+0xAAC/+0x15F8 via vtbl+0xF8), thumb rect via ScrollBar_thumb_rect, grip sprite via Sprite_draw_2(num=1,den=1) @0x6067ED centered in rect
extern void ScrollBar_on_resize(void* self, int w, int h);                     // addr: 0x00606860  observed  vtable[0x34], RET 8; b=+0xA60=min(w,h), rebuilds thumb zone +0xA4C, then resizes/moves ONLY the down arrow +0x15F8 (arms 0x6068DB plain / 0x606935 bordered) — the up arrow +0xAAC is never resized (vanilla bug)
extern void ScrollBar_thumb_rect(void* self, RECT* out);                       // addr: 0x00606C50  observed  thiscall; computes the proportional thumb rect
extern void ScrollBar_on_mouse_move(void* self, int x, int y);                 // addr: 0x00605D90  observed  vtbl+0x44 (vtable 0x669D58); DRAG: gates on g_pressed_win_l/r==self && g_click_pending && hit vs [self+0x474], zone [self+0xA44] (0=thumb drag, +/-1=page)
extern void ScrollBar_on_press(void* self, int x, int y);                      // addr: 0x006061E0  observed  vtbl+0x50; sets zone +0xA44 from thumb-rect cache +0xA4C..+0xA58, resets +0xA38, arms g_sb_track_win/g_sb_track_phase
extern void ScrollBar_on_release(void* self);                                  // addr: 0x00606310  observed  vtbl+0x4C
extern void ScrollBar_on_l_up(void* self, int x, int y);                      // addr: 0x006062C0  observed  thiscall RET 8; vtbl+0x54; redraw, clears g_sb_track_win
// field: ScrollBar +0xA38 int track_counter   repeat-delay counter (press resets)
// field: ScrollBar +0xA44 int press_zone      -1/0/+1 (0 = thumb drag mode)
// field: ScrollBar +0xA4C RECT thumb_zone     the current thumb rect = the press hit zone (rewritten by init_inner/subctor)
// field: ScrollBar +0xA20 int range_min       ScrollBar_set_range lower bound
// field: ScrollBar +0xA24 int range_max       ScrollBar_set_range upper bound
// field: ScrollBar +0xA28 int inverted        nonzero -> notified value = max - raw + min
// field: ScrollBar +0xA2C int value           raw position
extern struct Sprite* g_scrollbar_thumb_sprite;                                // addr: 0x009B8E1C  observed  grip Sprite* (=0x79A5E8, set @0x5887CC); copied to widget+0xA74 by ScrollBar_subctor
extern struct Sprite g_scrollbar_sprite_block[12];                             // addr: 0x00791D88  observed  12 Sprite objs stride 0x2C (arrows/track parts); ptrs installed at 0x9B8DE8..0x9B8E14 by the defaults writer @0x588754..0x5887CC
// field: TextScroll +0xA74 Sprite* sb_thumb_sprite   grip square; drawn 1:1 @0x6067ED
// field: TextScroll +0xAAC FlatButton sb_btn_up      label-less arrow mini-button
// field: TextScroll +0x15F8 FlatButton sb_btn_down   label-less arrow mini-button
extern void EditLine_ctor(void* self);                                         // addr: 0x00614E50  observed  edit-line widget ctor
extern int  EditLine_attach(void* self, ...);                                  // addr: 0x00614FE0  observed  thiscall; SHARED with FileDlg @0x613A64 + 0x611DB9/0x4446CF - scale ARGS at call site only
extern int  Win_set_modal(struct Win* self, int flag, void* fn, struct Win* parent); // addr: 0x005EE190  thinker   thiscall RET 0xC; vtable+0xE4 modal loop; pushes g_modal_stack/g_modal_depth, g_modal_top=this @0x5EE1C8; fn null-checked
extern void Win_release_modal(struct Win* self);                               // addr: 0x005EE280  thinker   fastcall(ecx=this); pops the modal stack, restores g_modal_top
extern int  g_modal_depth;                                                     // addr: 0x009B7AE4  thinker   Win_set_modal stack depth (max 4)
extern struct Win* g_modal_stack[4];                                           // addr: 0x009B6EF8  observed  Win_set_modal stack
extern struct Win* g_modal_parent[4];                                          // addr: 0x009B7A1C  observed  Win_set_modal parent args, parallel to g_modal_stack
extern int  Win_modal_always(void);                                            // addr: 0x00406840  observed  `mov eax,1; ret`; vtbl+0xEC of SetupWin/PrefWin (never self-terminates)
extern int  Win_on_key(struct Win* self, unsigned key, int down);              // addr: 0x005F5D10  observed  thiscall; vtbl+0x138; adds Shift/Ctrl/Alt bits 0x10000/0x20000/0x40000
extern void wait_task(void);                                                   // addr: 0x005FC700  thinker   cdecl; one pump step: WM_PAINT loop + PeekMessage(0..0x400 / 0x400..0xFFFF, PM_REMOVE) + dispatch
extern void wait_loop(void);                                                   // addr: 0x0051F200  thinker   cdecl; wait_task (SP) or NetDaemon tasks (MP); Console_human_turn idle pump
extern int  do_non_input(void);                                                // addr: 0x005FCA30  thinker   cdecl; removes+dispatches the oldest non-input message; 1 if one dispatched
extern void do_all_draws(void);                                                // addr: 0x005FCBB0  thinker   cdecl; pumps WM_PAINT only
extern void flush_input(void);                                                 // addr: 0x005FD120  thinker   cdecl; drops queued 0x100..0x108 and 0x200..0x209
extern struct Sprite g_mp_arrow_sprite;                                        // addr: 0x00788038  observed  dropdown-arrow Sprite OBJECT (lobby-exclusive); key byte @+8 (0x788040), height dword @+0x1C (0x788054); blitted via Sprite_blit_scaled_core x11 (3 roster sites x=rectR-0xA, 8 settings sites x=text_end+3)
extern struct Sprite g_mp_toggle_off;                                          // addr: 0x007AC040  observed  roster toggle Sprite OBJECT off/AI state (key @+8=0x7AC048); one shared Sprite_draw_2(...,1,1) CALL @0x480599
extern struct Sprite g_mp_toggle_on;                                           // addr: 0x007AC06C  observed  roster toggle Sprite OBJECT on/human state (key @+8=0x7AC074)
extern struct Font* g_default_font;                                            // addr: 0x009BB484  observed  engine default Font*; Buffer_ctor inits Buffer+0x52C from it (chat TextScroll 0x629B70 + EditLine 0x615270 draws use it when no set_font ran); NEVER overwrite the global
extern void* g_checkbox_sprite_table;                                          // addr: 0x007794E0  observed  checkbox sprite ptr table; SHARED with Popup_on_dialog_item_back_draw @0x405BCC - scale at blit sites, never the sprites
// field: NetWin +0x16c  int  title_h            =0x1A set @0x482616
// field: NetWin +0xA14  RECT title_bar           client(+0x474) inset 3, h 0x1A
// field: NetWin +0xA24  RECT settings_body       {7,0x3A,0x134,0x180}
// field: NetWin +0xA34  RECT settings_header     {7,0x24,0x134,0x38} game-name strip
// field: NetWin +0xA44  RECT settings_outer      UnionRect(+/-3) of A24/A34
// field: NetWin +0xA54  RECT players_header      {0x13D,0x24,0x319,0x38}
// field: NetWin +0xA64  RECT players_outer       {0x13A,0x21,0x31C,0xEB}
// field: NetWin +0xA74  RECT[7] row_name         {0x161,y,0x213,y+0x14} y0=0x3A pitch 0x16
// field: NetWin +0xAE4  RECT[7] row_faction      {0x215,y,0x2A1,y+0x14}
// field: NetWin +0xB54  RECT[7] row_handicap     {0x2A3,y,0x319,y+0x14}
// field: NetWin +0xBC4  RECT[7] row_toggle       {0x14F,y,0x15F,y+0x14}
// field: NetWin +0xC54  RECT[7] row_lock         {0x13D,y,0x14D,y+0x14}
// field: NetWin +0xC34  RECT btn_launch          {0x13D,0xD4,0x229,0xE8}
// field: NetWin +0xC44  RECT btn_cancel          {0x22C,0xD4,0x318,0xE8}
// field: NetWin +0xCC4  RECT chat_log            {0x13D,0xF1,0x319,0x162}
// field: NetWin +0xCD4  RECT chat_input          {0x13D,0x164,0x319,0x180}
// field: NetWin +0xCE4  RECT chat_outer          UnionRect(+/-3)
// field: NetWin +0xCF4  RECT options_header      {7,0x189,0x319,0x19D}
// field: NetWin +0xD04  RECT options_outer       UnionRect(+/-3)
// field: NetWin +0xD14  RECT options_col1        {0x1B,0x19F,0x18F,0x251}
// field: NetWin +0xD24  RECT options_col2        {0x1A5,0x19F,0x319,0x251}
// field: NetWin +0x4F7C struct FlatButton btn_launch_obj
// field: NetWin +0x5AC8 struct FlatButton btn_cancel_obj
// field: NetWin +0x1190 void* player_color_cb    =0x4832D0 set @0x482A16

// ============================================================================
// Pop-up menu control (universal right-click/dropdown menu; its OWN GraphicWin,
//   sized from g_menu_font + margins with NO g/16 scaling -> native-tiny at hi-res).
//   The faction-row dropdown SUBMENU (Choose Your Factions, ids 0x3039..0x303f) is
//   this control: FactionPickWin_on_command case>=0x3039 -> Menu_run. (N1 target.)
// ============================================================================
extern int  FactionPickWin_on_command(int self, int id);                       // addr: 0x00489BA0  observed  fastcall this=ECX; case id>=0x3039 (@0x48a08b) opens the row dropdown submenu via Menu_run @0x48a138
extern int  Menu_run(int self, int x, int y, int a4);                          // addr: 0x0059D250  observed  thiscall; builds+shows popup menu, returns chosen index
extern void Menu_begin(int a1, int a2);                                        // addr: 0x0059D3A0  observed  -> BasePop_init(0,0) (menu obj begin)
extern void Menu_init(int self, int a2);                                       // addr: 0x005F8920  observed  thiscall; -> GraphicWin_init(0,0,0,0) (size deferred to Menu_show)
extern int  Menu_add_item(int self, int id, const char* text);                 // addr: 0x005F89D0  observed  thiscall; append entry -> Menu_measure_width
extern void Menu_add_separator(int self, int id);                              // addr: 0x005F8BE0  observed  thiscall
extern void Menu_measure_width(int self, const char* text);                    // addr: 0x005F9D30  observed  thiscall; accumulates Font_width into self+0xf24
extern int  Menu_show(int self, unsigned x, unsigned y, int a4);               // addr: 0x005F9170  observed  thiscall; SIZE site (~0x5F918B): GraphicWin_resize from g_menu_font height/width + margins, NO g/16; then modal loop
extern void Menu_draw_dispatch(int self);                                      // addr: 0x005F9590  observed  GraphicWin content vtable -> Menu_draw
extern void Menu_draw(int self, int hot_idx, int prev_idx);                    // addr: 0x005F9F60  observed  thiscall; rows/highlight/separators; row pitch = Buffer_text_line_height (font-derived)
extern void Menu_ctor(int self);                                                // addr: 0x005F8800  observed  thiscall; GraphicWin_ctor + vtbl 0x66FF40
extern void Menu_paint(int self);                                               // addr: 0x005F98B0  observed  thiscall; Menu vtbl+0x30
extern void* Menu_vtbl[];                                                       // addr: 0x0066FF40  observed  universal Menu control vtbl; +0x30 Menu_paint, +0xE4 Win_set_modal
extern void Menu_on_select(int* self, int id);                                 // addr: 0x005FB830  observed  thiscall; fires selected item callback
extern struct Font* g_menu_font;                                               // addr: 0x009B7B68  observed  Font* sizing+drawing the menu (=g_popup_menu_font_src; find_font(0x10) capped >=1024 -> 16pt)
extern struct Font* g_popup_menu_font_src;                                     // addr: 0x009457EC  observed  config_popups: SW==800?12pt:16pt; copied to g_menu_font
extern int  g_menu_margin_v;                                                   // addr: 0x00696E1C  observed  menu vertical margin (=1; *2 in width/height formula)
extern int  g_menu_margin_h;                                                   // addr: 0x00696E04  observed  menu horizontal/left margin
// ---- mouseover tooltip ("bubble") ----
extern void Win_set_bubble_text(void* self, char* text, RECT* anchor);         // addr: 0x005F83D0  observed  thiscall RET 0x8; computes bubble box from g_bubble_font (margin=Font_width(font,@0x696E00)*2, line h=font[3]/[4]+[0]), centres over anchor + clamps to ScreenWidth, stores rect g_bubble_rect + text g_bubble_text
extern void Win_clear_bubble_text(void);                                       // addr: 0x005F8500  observed  clears g_bubble_text/g_bubble_owner; repaints via overlay_compositor
extern int  BaseButton_set_bubble_text(void* self, char* text);                // addr: 0x00607550  observed  thiscall; attaches hover bubble text to a button (faction preview boxes id 0x100/0x101/0x102 use strings 0x116c/0x1170/0x1174)
extern void overlay_compositor(RECT* clip);                                    // addr: 0x005EFD20  observed  per-frame overlay paint; if g_bubble_text: Buffer_box_2 border (color 0x696D30) + 1px inset + Buffer_fill_3 + Buffer_set_font(g_bubble_font) + Buffer_write_cent_l_7; then cursor sprite + HDC BitBlt
extern struct Font* g_bubble_font;                                             // addr: 0x009B7A54  observed  Font* for ALL mouseover tooltips; config_popups sets = find_font(0xc,0); bubble box geometry + text both derive from it (lever for tooltip scaling)
extern char* g_bubble_text;                                                    // addr: 0x009B7A50  observed  current bubble text ptr (NULL = no bubble); '^' = line break
extern void* g_bubble_owner;                                                   // addr: 0x009B7A4C  observed  Win* that owns the current bubble
extern RECT g_bubble_rect;                                                     // addr: 0x009B6E38  observed  computed bubble box {l,t,r,b} at 0x9B6E38/3C/40/44
// field: Menu +0xf20 int item_alloc_count    ; capped 0x40
// field: Menu +0xf24 int content_width        ; max Font_width over items (feeds Menu_show width)
// field: Menu +0xf2c int visible_item_count   ; * font cell-height = menu height
// field: Menu  item record stride = 0x14 (text@+0xa18, alt@+0xa1c, id@+0xa20, flags@+0xa24)

// ============================================================================
// FlatButton (popup option buttons)
// ============================================================================
extern void FlatButton_ctor(struct GraphicWin* self);                          // addr: 0x00607CF0  observed  sets vtable 0x00669754; defaults 9x3 frame pieces from g_default_btn_frame_sprites
extern void FlatButton_content_draw(struct GraphicWin* self);                  // addr: 0x00607E50  observed  vtable[0x30]; draws bar + text
extern void BaseButton_init(struct GraphicWin* self, const char* text, int a3, int x, int y, int w, int h, void* parent, int a9); // addr: 0x00607210  observed  -> GraphicWin_init
extern struct FlatButton FlatButtons[];                                        // addr: 0x007AF620  observed  HUD button array (=MainWin+0xE00, stride 0xB4C): [0] 0x3E8 MESSAGES 0x7AF620, [1] 0x3E9 INFO 0x7B016C, [2] 0x3EA TOOLBAR 0x7B0CB8, [3] 0x3EB MENU 0x7B1804, [4] 0x3EC COMMLINK 0x7B2350
extern struct FlatButton btn_world_map;                                        // addr: 0x007B39E8  observed  =MainWin+0x51C8, id 0x3EE, 54x32; box-10 planet button (init @0x45AD46, rect MainWin+0xA8C)
extern struct FlatButton btn_detail_map;                                       // addr: 0x007B4534  observed  =MainWin+0x5D14, id 0x3EF, 54x32; box-10 planet button (init @0x45ADBF, rect MainWin+0xA9C)
extern void FlatButton_on_mouse_move(struct FlatButton* self);                 // addr: 0x00608500  observed  vtable[0x44]; hit-tests +0x474, sets/clears hover_flag +0xA74, then calls vtable[0xF8] GraphicWin_redraw -> content_draw via vtable[0x30] (the SAME slot ScrollBar_draw uses, so hover repaints are subject to the same zoom arming)
extern void FlatButton_on_mouse_move_2(struct FlatButton* self);               // addr: 0x00608660  observed  vtable[0x48]; twin used while another window holds the press; also clears hover and redraws
// field: FlatButton +0xA74 int hover_flag        nonzero -> draw state 1 when +0xAB8 outside 0..2
// field: FlatButton +0xA18 int pressed_flag_a    with +0xA9C: either nonzero -> draw state 2
// field: FlatButton +0xA9C int pressed_flag_b    see +0xA18
// field: FlatButton +0xA88 int bevel_color_h     ; flat-path bevel loop Buffer_box_2 arg (swapped with +0xA8C when pressed)
// field: FlatButton +0xA8C int bevel_color_v     ; see +0xA88
// field: FlatButton +0xA90 int bevel_count       ; flat-path concentric box_2 iterations (1px inset each); pressed also shifts rect by this
// field: FlatButton +0xA94 int border_color      ; -1 = none; else 1 outer box_2 + inset (2nd box if focused)
// field: FlatButton +0xAB8 int forced_state      ; 0..2 overrides the hover/pressed-derived draw state
// field: FlatButton +0xAC8 BoxSpriteParams* boxParams[3]   per-state Buffer_box_sprite sets on the +0x474 rect (TOOLBAR + DL BACK/EXIT/wings: 0x78D960/88/B0); 2nd priority after stateSprites; when taken, content_draw SKIPS the bevel loop (jmp 0x608365)
// field: BoxSpriteParams +0x00 Sprite* corners[4]   TL/TR/BL/BR (DL faces 6x6, 1px stroke on outer edge, corner px keyed 9, interior idx 7 pass-through)
// field: BoxSpriteParams +0x10 Sprite* edges[4]     top/bottom (24x6) then left/right (6x24); 1px stroke at the outer row/col, rest idx 7
// field: BoxSpriteParams +0x20 Sprite* fill         DL faces: degenerate (+0 = 0x66fdbc proc)
// field: FlatButton +0xAD4 Sprite* stateSprites[3] per-state single sprite, drawn centered (MENU/COMMLINK band 106x14: MainWin+0x21D7C/0x21DA8/0x21DD4, extracted @0x45A38D); 1st priority
// field: FlatButton +0xAE0 Sprite* framePieces[9][3]  piece-major, 3 states each: +0xAE0 L, +0xAEC R, +0xAF8 T, +0xB04 B, +0xB10 TL, +0xB1C TR, +0xB28 BL, +0xB34 BR, +0xB40 fill (fill draws only if all 8 others present); ctor defaults from g_default_btn_frame_sprites (defaults populate ONLY T/TL/TR, 67x20/3x20/3x20 per state, extracted in load_interface @0x455610 loop)

// ============================================================================
// Flic animation player (turn.flc TURN COMPLETE band etc.)
// ============================================================================
extern void Flic_ctor(void* self);                                             // addr: 0x00629D60  observed  thiscall
extern void Flic_dtor(void* self);                                             // addr: 0x00629DF0  observed  thiscall
extern int  Flic_init(void* self, struct Buffer* dst, const char* path, int x, int y, int a6); // addr: 0x00629E50  observed  thiscall RET 0x14; w/h from FLC header -> +0x59C/+0x5A0; own 0x5DFF00 call @0x62A046 = background capture (dst->canvas)
extern int  Flic_draw_frame(void* self, int x, int y);                         // addr: 0x0062A070  observed  thiscall; stores x,y -> +0x5AC/+0x5B0 then Flic_decode_chunk; pixel chunks write dst DIRECTLY (canvas->dst blit @0x62ADED Buffer_copy_4 = BG RESTORE, gated byte [self+0]!=0)
extern int  Flic_draw_frame_once(void* self);                                  // addr: 0x0062A120  observed  thiscall
extern int  Flic_advance(void* self);                                          // addr: 0x0062A210  observed  thiscall
extern int  Flic_rewind(void* self);                                           // addr: 0x0062A280  observed  thiscall; file-seek to frame 0 only, no draw
extern int  Flic_decode_chunk(void* self);                                     // addr: 0x0062ACD0  observed  thiscall; per-chunk-type handlers (full-frame handler @0x62AD86; dispatch jump table @0x62AF18 via byte map @0x62AF30, chunk types 4..18)
extern int  Flic_decode_keyed_frame(void* self);                               // addr: 0x0062B670  observed  thiscall; KEYED-mode type-16 COPY (E8 @0x62ADF9): reads w*h bytes from file, writes dst at dstX/dstY; pixel==key byte [self+0] -> substitutes canvas bg pixel; sets dirty +0x58C..+0x598
extern int  Flic_decode_brun(void* self);                                      // addr: 0x0062A500  observed  thiscall; DIRECT-mode type-15 BYTE_RUN -> writes dst; E8 @0x62AE32
extern int  Flic_decode_ss2(void* self);                                       // addr: 0x0062A720  observed  thiscall; DIRECT-mode type-7 DELTA_FLC (SS2) -> writes dst; E8 @0x62AE26
extern int  Flic_decode_copy(void* self);                                      // addr: 0x0062AB80  observed  thiscall; DIRECT-mode type-16 COPY -> writes dst; E8 @0x62AE9A
extern int  Flic_decode_brun_keyed(void* self);                                // addr: 0x0062AF40  observed  thiscall; KEYED-mode type-15 BYTE_RUN (E8 @0x62AD7C) -> writes dst, key pixels take canvas bg; turn.flc frame 0's actual painter
extern int  Flic_decode_ss2_keyed(void* self);                                 // addr: 0x0062B190  observed  thiscall; KEYED-mode type-7 SS2 delta (E8 @0x62AD70)
extern int  MainWin_turn_banner_refresh(void* self);                           // addr: 0x0045C3A0  observed  thiscall(ecx=MainWin); TURN COMPLETE band+text; Spot_get_rect slot 5 @0x45C425; anim path Flic_draw @0x45C499, static/disarm path Flic_rewind+Flic_draw @0x45C4C7; text @0x45C596; flush @0x45C5A4; callers 0x421C5D/0x422CA4/0x45BE71/0x45D04C/0x45D0F9/0x45D136
// field: Flic +0x000 char blitGate    0 = skip the 0x62ADED canvas->dst BG-RESTORE blit; ALSO the transparency key byte in Flic_decode_keyed_frame
// field: Flic +0x004 Buffer canvas    background patch ONLY: w x h texels of dst at (x,y) captured at Flic_init whatever dst's scale (decoded frames never land here — pixel handlers write dst directly)
// field: Flic +0x59C int w            from FLC file header (turn.flc = 233)
// field: Flic +0x5A0 int h            from FLC file header (turn.flc = 23)
// field: Flic +0x5A8 Buffer* dst      blit destination (turn.flc: strip buffer 0x7AEC64)
// field: Flic +0x5AC int dstX         from Flic_init x (turn.flc: MainWin+0xA7C rect L)
// field: Flic +0x5B0 int dstY         from Flic_init y
// field: Flic +0x5B4 int flags        bit0 = loaded; bit1 = KEYED/transparent decode mode -> sub-chunk dispatch uses keyed table @0x62AEF0 (map @0x62AF08) instead of direct @0x62AF18 (map @0x62AF30); Flic_draw_frame_once forces bit1 for one draw; turn.flc runs with it SET
// field: Flic +0xA10 int frameIdx

// ============================================================================
// Audio (Wave)
// ============================================================================
extern void Wave_ctor(void* self);                                             // addr: 0x004C66E0  thinker   thiscall
extern void Wave_dtor(void* self);                                             // addr: 0x004C67C0  thinker   thiscall
extern void Wave_load(void* self, const char* name);                           // addr: 0x004C6C20  thinker   thiscall
extern int Wave_load_3(void* self, char* name, unsigned flags);                // addr: 0x004C6DB0  thinker   thiscall RET 8; flags 2 = streaming (menu music/credits)
extern void Wave_play_2(void* self);                                           // addr: 0x004C6920  thinker   thiscall
extern int Wave_is_playing(void* self);                                        // addr: 0x004C6B10  thinker   thiscall; null-safe on a never-loaded wave
extern int Wave_unload(void* self);                                            // addr: 0x004C6EA0  thinker   thiscall
extern char g_credits_wave[];                                                  // addr: 0x00703E30  observed  credits-private static Wave; loads "fx\opening menu.wav" (0x68328C)
extern char g_menu_music_wave[];                                               // addr: 0x00945780  observed  top_menu's Wave streaming "fx\opening menu.wav" (load+play 0x58E3D2)
extern void* g_music;                                                          // addr: 0x0074DAA0  observed  in-game .amb music object
extern char g_sound_mgr[];                                                     // addr: 0x0090D978  observed  sound manager; device at +0x14
extern void SoundMgr_suspend(void* self);                                      // addr: 0x004C4FC0  observed  thiscall; device vtbl+0x48
extern void SoundMgr_resume(void* self);                                       // addr: 0x004C4FD0  observed  thiscall; device vtbl+0x4C
extern int SoundMgr_pause(void* self);                                         // addr: 0x004C51D0  observed  thiscall; device vtbl+0x64
extern int SoundMgr_unpause(void* self);                                       // addr: 0x004C51C0  observed  thiscall; device vtbl+0x60
extern void* g_input_callback;                                                 // addr: 0x009B7A88  observed  WinProc input hook

// ============================================================================
// Movie playback (PRACX runtime-hooks amovie_project_2 entry -> PRACXShowMovie)
// ============================================================================
extern void amovie_project(int idx);                                           // addr: 0x00403BA0  thinker   cdecl; by-index wrapper, resolves name then calls amovie_project_2 @0x403BD4
extern void amovie_project_2(const char* name);                                // addr: 0x00403BE0  thinker   cdecl; movies\<name>.wve found -> set_video_mode (IN-EXE EA uV/TGV player, DDraw excl-fullscreen 640x480); fallback exts -> Movie_player (MCI avivideo)
extern int set_video_mode(void* self, const char* path, int w, int h, int flags); // addr: 0x004BEA50  observed  thiscall; MISNOMER: plays a FULLSCREEN .wve via the in-exe uV player -- movie_ddraw_fs_init (mode set) then movie_play_open + msg-pump (ESC/Enter/Space/click skip); called @0x403CC0 + @0x403D8C
extern int movie_ddraw_fs_init(void* self, int w, int h);                       // addr: 0x004BF4B0  observed  thiscall; DirectDrawCreate -> SetCooperativeLevel(phWnd, DDSCL_EXCLUSIVE|DDSCL_FULLSCREEN=0x11) -> IDirectDraw2::SetDisplayMode(640,480,16->24->32->8). Own DDraw device; desktop reflow ONLY if game is at desktop res non-exclusive (PRACX / DirectDraw=0), harmless within an already-exclusive 1024x768 session (DirectDraw=1)
extern int* movie_play_open(const char* path, int hwnd, int* ctx);             // addr: 0x005CAE80  observed  cdecl; in-exe EA uV/TGV player entry: uv_container_open + uv_dsound_init + uv_ddraw_surfaces, spawns uv_decode_thread; plays into phWnd
extern int uv_container_open(const char* path, int* ctx);                      // addr: 0x005CB050  observed  fastcall; mmioOpenA + EA magic check (SEAD/SCHl/1SNh), allocs 1.2MB frame + 300KB audio buffers, primes via uv_decode_frame
extern int uv_decode_frame(unsigned hdr);                                      // addr: 0x005C9EC0  observed  thiscall(ecx=ctx); reads 8-byte EA chunk hdr (mmioRead), dispatches on 4CC (SCHl/SCCl/SDCl/SECl/TGV*); returns -1 EOF / type code; the demux+decode core
extern void uv_decode_thread(int* ctx);                                        // addr: 0x005CB220  observed  fastcall; decode/present worker (SetThreadPriority), 24-frame ring, loops uv_decode_frame -> uv_present_frame; state @[*ctx+0x98] (1 start/2 run/3 pause/4 stop/5 done)
extern void uv_present_frame(int* ctx);                                        // addr: 0x005CC940  observed  fastcall; blits a decoded frame to the DDraw video surface
extern int uv_dsound_init(int* ctx);                                           // addr: 0x005CE340  observed  fastcall; DirectSoundCreate + SetCooperativeLevel; movie audio output
extern void uv_ddraw_surfaces(int* ctx);                                       // addr: 0x005CBE30  observed  fastcall; creates the DDraw video surfaces (QI IDirectDraw2)
extern int uv_is_playing(int* ctx);                                            // addr: 0x005CB610  observed  cdecl; true while state != 6/done; polled by set_video_mode pump loop
extern void MovieFS_ctor(void* self);                                          // addr: 0x004BEA30  observed  thiscall; fullscreen-movie object (0xE68 bytes) ctor
extern void movie_caption(void* self);                                         // addr: 0x004BEF00  observed  thiscall; post-movie caption from movlist.txt #<NAME>; sole caller 0x4BED47 inside set_video_mode
extern void movie_caption_type_char(const char* s, int x, int y, int len);     // addr: 0x004BEE60  observed  cdecl; Buffer per-string callback: one char per Buffer_write_raw_l then busy-wait delay ms
extern int movie_skip_poll(void);                                              // addr: 0x004BF390  observed  uV player skip callback
extern int g_movie_skipped;                                                    // addr: 0x008CC250  observed  1 = movie skipped (suppresses movie_caption)
extern void* g_movie_fs_cur;                                                   // addr: 0x008CC254  observed  current fullscreen-movie object
extern struct Palette* g_game_palette;                                         // addr: 0x009B8174  observed  current game palette; PALETTEENTRY[256] at +0
// field: MovieFS +0x000 char[] name   uppercased movie basename = movlist section key
// field: MovieFS +0x110 void* dd_primary   IDirectDrawSurface* 640x480 primary
// field: MovieFS +0x8DC Buffer caption_buf   wraps dd_primary (Buffer_init flags 4)
// field: MovieFS +0xE64 int char_delay_ms   typewriter ms per char
extern void Movie_player(void* self);                                        // addr: 0x00404070  observed  SEPARATE legacy/fallback path: GraphicWin_init own window then MCI avivideo (NOT used for movies\*.wve)
extern void Movie_mci_open(void* self);                                        // addr: 0x005FFF90  observed  mciSendCommandA MCI_OPEN device "avivideo"(@0x696E94); pulls 256-entry palette (MCI_STATUS), MCI_WHERE/MCI_PUT rect, subclasses MCI window
extern void Movie_mci_play(void* self);                                        // addr: 0x006001E0  observed  mciSendCommandA MCI_WINDOW + MCI_PLAY
extern void Movie_mci_stop_close(void* self);                                  // addr: 0x005FFDB0  observed  generic movie teardown (MCI_WINDOW/MCI_STOP/MCI_CLOSE); also called on the uV path
extern char playuv_copyright[];                                                // addr: 0x00691F08  observed  "Play uV/uV2 Version 1.50, Martin Griffiths, EA UK 1997" -- dead STRING (no xref), but the uV player CODE (uv_* above) IS linked + active
extern void movie_ddraw_fs_teardown(void* self);                               // addr: 0x004BF400  observed  thiscall; native movie EXIT: IDirectDraw2::RestoreDisplayMode -> Release(surface) -> Release(ddraw) -> Win_set_display_mode(gameW,gameH,8,0). The final call is MANDATORY: it re-runs the game's video-mode init so the scaled fullscreen returns (without it the game stays at the bare DDraw mode = tiny/black). uimod's pristine DDraw presenter teardown mirrors this exactly.
extern void Win_set_display_mode(int w, int h, int bpp, int flags);            // addr: 0x005F2C40  observed  cdecl; (re)initialise the game's display mode -> GraphicsMgr_set_mode on global graphics manager @0x9BE618. Call (w,h,8,0) after releasing any foreign DDraw device to restore the game's scaled screen.
extern void GraphicsMgr_set_mode(void* self, int w, int h, int bpp, int flags);// addr: 0x00635510  observed  thiscall(ecx=g_graphics_mgr 0x9BE618); the method Win_set_display_mode wraps

// ============================================================================
// PRACX bootstrap / DLL load mechanism (in _SELFMOD; pracxpatch-installed)
// ============================================================================
extern void PRACX_load_stub(void);                                             // addr: 0x00668160  observed  void(void) in _SELFMOD: LoadLibraryA("prax")->GetProcAddress(h,ord#1)->init(h)[__stdcall]->ret @0x668189; ends 0x66818A=zero-filled free space
extern char PRACX_dll_name[5];                                                 // addr: 0x00668165  observed  inline "prax\0" pushed via call$+5 trick @0x668160 (LoadLibraryA appends .dll)
extern void* g_startup_init_table;                                             // addr: 0x00682000  observed  MSVC C++ initializer table (_initterm pfbegin); extent 0x682000..0x6826cc. entry[0]: PRACX=PRACX_load_stub(0x668160), PRISTINE=NULL (the free slot uimod_bootstrap_native fills); entries[1..]=game init funcs (0x402f10,0x40444x...)
extern void _initterm(void** pfbegin, void** pfend);                           // addr: 0x00644ED8  observed  __cdecl MSVC CRT _initterm; walks pfbegin..pfend, calls each non-null _PVFV (skips nulls). Driven from 0x644ddd (pushes 0x682000/0x6826cc). uimod native loader rides entry[0].
extern void* IAT_LoadLibraryA;                                                 // addr: 0x00669120  observed  KERNEL32 LoadLibraryA IAT slot (used by PRACX_load_stub + uimod_native_stub)
extern void* IAT_GetProcAddress;                                               // addr: 0x00669124  observed  KERNEL32 GetProcAddress IAT slot (used by PRACX_load_stub + uimod_native_stub)
extern void* IAT_GetCursorPos;                                                 // addr: 0x00669284  observed  USER32 GetCursorPos IAT slot
extern void* IAT_ScreenToClient;                                               // addr: 0x006692D4  observed  USER32 ScreenToClient IAT slot
extern void uimod_native_stub(void);                                           // addr: 0x00668160  observed  void(void) in free _SELFMOD (pristine cc659f only): LoadLibraryA("uimod")->GetProcAddress(h,ord#1=Init)->Init(h)[__stdcall]->ret. Installed by patches.yaml group uimod_bootstrap_native; reached via g_startup_init_table[0].

// ============================================================================
// Statically-linked MSVC CRT (Win11 24H2 file-lock crash site; see memory)
// ============================================================================
extern void crt_malloc(int size);                                              // addr: 0x0064558A  observed  cdecl (Ghidra names it operator_new)
extern int  crt_strlen(const char* s);                                         // addr: 0x006453E0  observed  cdecl
extern void crt_free(void* p);                                                 // addr: 0x0064557F  observed  cdecl (operator_delete -> free 0x644EF2; NULL ok)
extern long crt_ftol(void);                                                    // addr: 0x006458C8  observed  MSVC _ftol: st0 -> edx:eax truncated, pops
extern void _lock_file(void* file);                                            // addr: 0x00647C37  observed  cdecl; per-FILE lock
extern void _unlock_file(void* file);                                          // addr: 0x00647C89  observed  cdecl; per-FILE unlock
extern void _getstream(void);                                                  // addr: 0x00649778  observed  cdecl; malloc(0x38) _FILEX, embedded CS at +0x20

// ============================================================================
// Globals (data)
// ============================================================================
extern struct Buffer DAT_buffer_interface;    // addr: 0x00798668  observed  src Buffer for load_interface (iface.pcx + interface.pcx)
extern void* caption_draw_callback;           // addr: 0x009B33C0  observed  current caption renderer (set to def_caption_draw)
extern int32_t font_size_table[12];           // addr: 0x0068F220  observed  {40,36,32,24,22,20,18,16,14,12,10,8}; find_font search domain
extern int32_t font_variant_flags[4];         // addr: 0x0068F250  observed  {0,1,2,4}
extern struct Font font_object_table[12][4];  // addr: 0x0093FC58  observed  row stride 0xA0 (4 variants * 0x28)
extern int32_t g_view_x;                      // addr: 0x00933454  observed  map view origin tile X (WorldWin/draw_box view anchor)
extern int32_t g_view_y;                      // addr: 0x00933458  observed  map view origin tile Y
extern int32_t g_scroll_susp1;                // addr: 0x0093345C  observed  scroll-in-progress suppressor #1; read ONLY by WorldWin_draw_box; nonzero mid-scroll
extern int32_t g_scroll_susp2;                // addr: 0x00933460  observed  scroll-in-progress suppressor #2; paired with g_scroll_susp1
extern int32_t g_view_w;                      // addr: 0x0093347C  observed  viewport width in tiles (Vw); draw_box gate g_view_w!=0
extern int32_t g_view_w3;                      // addr: 0x00933484  observed  viewport east-extent width component (Vw3); box spans full map when g_view_w+g_view_w3 >= g_map_width_tiles
extern int32_t g_map_width_tiles;             // addr: 0x00949870  observed  map width in tiles (mapW; 80 on a standard map)
extern int* MapOceanCoverage;                 // addr: 0x0094A2A4  thinker
extern int* MapLandCoverage;                  // addr: 0x0094A2A8  thinker   2 - MapOceanCoverage
extern int* MapErosiveForces;                 // addr: 0x0094A2AC  thinker
extern int* MapCloudCover;                    // addr: 0x0094A2B4  thinker
extern int* MapNativeLifeForms;               // addr: 0x0094A2B8  thinker
extern struct CWorldbuilder* WorldBuilder;    // addr: 0x009502A8  thinker   124 bytes
extern int32_t SCALE_NUM_G;                   // addr: 0x00696D18  observed  engine screen-scale numerator (g; 16=native) used by Sprite_blit_scaled_core
extern int32_t SCALE_DEN_G;                   // addr: 0x00696D1C  observed  engine screen-scale denominator (16)
extern int32_t g_sprite_scale_cache_num;      // addr: 0x00696D20  observed  last-rebuilt SCALE_NUM_G; ==current -> the 8 blit-core copies skip the float+run-table rebuild
extern int32_t g_sprite_scale_cache_den;      // addr: 0x00696D24  observed  last-rebuilt SCALE_DEN_G (cache pair)
extern float   g_sprite_scale_float;          // addr: 0x009B6624  observed  num/den as float; sizes the scaled dest rect (fmul in all 8 blit-core copies); written BEFORE the limit check (the stale-float reject bug)
extern double  g_sprite_scale_max;            // addr: 0x0066FDC8  observed  = 4.0; max supported blit upscale ratio (fcomp in the 8 rebuild blocks; greater -> blit rejected)
extern int32_t g_sprite_scale_runs[];         // addr: 0x009B3AD8  observed  master per-src-index dest-run-length table for the current ratio (Sprite_fill_scaling_table); walked by both clipped-table builders on BOTH axes
extern struct Sprite g_buffer_blit_sprite;    // addr: 0x009B3A50  observed  Buffer_draw_2's stack-less sprite view of its src Buffer (name=0, data+4, key+8, pitch+0xC, w+0x10, h+0x14)
extern unsigned char g_ui_transparency_key;   // addr: 0x00696D14  observed  = 9; GraphicWin_fill bg + sprite-extract key
extern int32_t g_banner_animating;            // addr: 0x0068526C  observed  1 while the TURN COMPLETE flic loops (set @MainWin_turn_banner_refresh)
extern int32_t g_console_mode_id;             // addr: 0x007CD11C  observed  selected M/I/TOOLBAR mode button id (0x3E8/0x3E9/0x3EA)
extern int32_t GameState;                     // addr: 0x009A64C0  thinker   bit 0x40 scenario editor, 0x80 omniscient view, bit 2 turn-banner animating
extern struct Sprite* g_default_btn_frame_sprites[27]; // addr: 0x009B8E44  observed  9 frame pieces x 3 states; FlatButton_ctor defaults +0xAE0.. from it
extern struct Sprite g_btn_art_default[3][3];   // addr: 0x0077A8E0  observed  default FlatButton TL/T/TR art per state

// ============================================================================
// 9-slice band-map enlarge (cave pcave2; src work\scripts\assemble_bandmap.py)
// ============================================================================
extern void thunk_fe_bandmap();                                                // addr: 0x00A16210  observed  stashes g_band_nx/ny + g_bm_dstw/h from renderer [ebp-8] params / [ebp+8] rect, push;ret -> thunk_frame_enlarge
extern void thunk_bandmap_blit();                                              // addr: 0x00A16300  observed  cdecl(srcBuf,destBuf,srcX,srcY,srcW,srcH,dstX,dstY,dstW,dstH,key) RET 0x2C; drop-in for thunk_keyed_stretch_blit
extern int  g_band_nx;                                                         // addr: 0x00A16200  observed  one-shot native band depth X (TL corner canvas_w); 0 = fall back to the NN blit
extern int  g_band_ny;                                                         // addr: 0x00A16204  observed  one-shot native band depth Y (canvas_h)
extern int  g_bm_dstw;                                                         // addr: 0x00A16208  observed  one-shot exact-fill span W = (R+D)-X+1; consumed+cleared by thunk_bandmap_blit
extern int  g_bm_dsth;                                                         // addr: 0x00A1620C  observed  one-shot exact-fill span H = (B+D)-Y+1
extern unsigned short g_bm_fx[4096];                                           // addr: 0x00A13000  observed  dest->src column map, built per blit
extern unsigned short g_bm_fy[2048];                                           // addr: 0x00A15000  observed  dest->src row map
extern unsigned char  g_bm_fwdx[256];                                          // addr: 0x00A16000  observed  native band index per dest offset, X axis
extern unsigned char  g_bm_fwdy[256];                                          // addr: 0x00A16100  observed  same, Y axis

// ============================================================================
// QUIT-class (type-16) option-row gap (cave pcave2; src work\scripts\assemble_q16gap.py)
// ============================================================================
extern void thunk_q16_rowgap();                                                // addr: 0x00A16740  observed  CALL-helper @Site B 0x60d731 (eax=Dialog base); writes gap [D+0x44]=max(0,half_down(22*g,16)-rowH), returns ecx=pitch; g<=16 or rowH<=0 -> native; clobbers ecx/edx
// field: Dialog +0x20 uint flags     bit0 fixed height (+0x30), bit1 fixed width (+0x2C); set by Dialog_init_2 / Dialog_init_3 and for anchored popups
// field: Dialog +0x40 int bar_x      row-bar x inset
// field: Dialog +0x4C int columns    type-16 column count
// field: Dialog +0x50 int max_rows   type-16 rows-per-column cap
// field: Dialog +0x58 int rows_per_col  min(count, +0x50)
// field: Dialog +0x60 int content_h  = (rowH + gap) * count; copied -> popup[+0x30c4]
// field: Dialog +0x68 int rowH       row height; Buffer_text_height natively, Buffer_text_line_height at g>16

// ============================================================================
// Struct field offsets (byte offsets from the object base)
// ============================================================================
// field: Buffer +0x08 int (*pfcnScrollText)(char*,int,int,int)   per-buffer text callback (Thinker name); 0 normally — a nonzero garbage value here = stack/trampoline corruption canary
// field: Buffer +0x20 RECT clip                  ; +0x20..0x2c; BaseWin draw fns save it at entry (canvas+0x20 = BaseWin+0x464) and restore via their closing set_clip
// field: Buffer +0x30 RECT bounds                ; +0x30..0x3c; buffer-extent rect in the buffer's own (device) space; BaseWin+0x474 = canvas bounds (draw_energy_alloc header-box seed)
// field: Buffer +0x50 void* active_canvas        ; latched from +0x54 by each draw primitive; 0 when unlocked (set_clip vcalls [vtbl+4] if nonzero)
// field: Buffer +0x54 void* data                 ; pixel(x,y) = data + x + y*stride (8-bit palette idx); DIB-section bits from Buffer_init
// field: Buffer +0x58 void* surface              ; DDraw/DIB sub-object (0 = plain GDI buffer); vtbl +0x0C resize / +0x44 get-hdc / +0x68 release-hdc
// field: Buffer +0x60 HDC hdc_cur                ; cached blit HDC (zeroed when +0x68 refcount hits 0)
// field: Buffer +0x64 HDC mem_dc                 ; persistent CreateCompatibleDC (GDI mode)
// field: Buffer +0x68 int32 hdc_refcount         ; Buffer_copy_3 leaks src +1 per call (dest balanced)
// field: Buffer +0x6C int32 draw_lock_refcount   ; inc'd/dec'd per hline/vline/box primitive call
// field: Buffer +0x78 HBITMAP dib                ; CreateDIBSection handle
// field: Buffer +0x4a4 int32 palette_gen         ; last-synced palette generation stamp (vs Palette +0x400)
// field: Buffer +0xA4 RGBQUAD dib_colors[256]    ; the buffer's own synced DIB color table (b,g,r,0) = per-context display truth (thunk_portrait_avg palette source)
// field: Palette +0x400 int32 generation         ; bumped on palette change; compared by Buffer_sync_to_palette
// field: Buffer +0x80 int32 width
// field: Buffer +0x84 int32 height               ; negative = top-down
// field: Buffer +0x4a8 int32 stride
// field: Buffer +0x52C Font* font0               ; set_font arg1; draw refused if [font+8] HFONT null
// field: Buffer +0x530 Font* font1               ; set_font arg2 (variant)
// field: Buffer +0x534 Font* font2               ; set_font arg3 (variant)
// field: Buffer +0x538 Font* font3               ; set_font arg4; wmfr_l link-height font
// field: Buffer +0x510 int   text_style          ; markup style 0..3 -> font slot +0x52C+4*style
// field: Buffer +0x51C int   link_state          ; $LINK parse state
// field: Buffer +0x520 int   markup_enable       ; 0 -> wmfr_l bypasses parsing to Buffer_write_raw_l
// field: Buffer +0x54C int   shadow_color        ; -1 = no shadow pass
// field: Buffer +0x55C int   shadow_dx           ; 2
// field: Buffer +0x56C int   shadow_dy           ; 2
// field: BaseWindow +0x40E8C Font fontShared14   persistent Arial-Narrow 14 bold (Font_init @0x41F2A1, style 1); header font for center fns AND strip-side queue/supported
// field: Sprite +0x4 uint8* data                 ; 8-bit pixel plane, row = data + y*pitch
// field: Sprite +0x8 uint8 key                   ; transparent index
// field: Sprite +0xc int32 pitch                 ; row pitch of data (what Sprite_blit_scaled_core steps by)
// field: Sprite +0x10 int32 blit_w               ; opaque content width (the blit width)
// field: Sprite +0x14 int32 blit_h               ; blit height
// field: Sprite +0x18 int32 canvas_w             ; logical canvas incl. transparent margins — NOT the blit width
// field: Sprite +0x1c int32 canvas_h
// field: Sprite +0x20 int32 off_x                ; content offset within canvas (draw x += off_x)
// field: Sprite +0x24 int32 off_y
// field: Sprite +0x28 int32 pixels_not_owned    ; 1 = +0x04 not the sprite's malloc (Sprite_extract_2 pool path); Sprite_close / a re-extract skip the free
// field: Sprite +0x30 uint8* mask                ; binary transparency plane (key=9)
// field: BoxSpriteParams +0x00 Sprite* corner_TL ; 10-dword 9-slice set for Buffer_box_sprite
// field: BoxSpriteParams +0x04 Sprite* corner_TR
// field: BoxSpriteParams +0x08 Sprite* corner_BL
// field: BoxSpriteParams +0x0c Sprite* corner_BR
// field: BoxSpriteParams +0x10 Sprite* edge_top  ; tiled
// field: BoxSpriteParams +0x14 Sprite* edge_bot
// field: BoxSpriteParams +0x18 Sprite* edge_left
// field: BoxSpriteParams +0x1c Sprite* edge_right
// field: BoxSpriteParams +0x20 Sprite* fill       ; 0 = hollow frame
// field: BoxSpriteParams +0x24 int32   fill_param ; mask colour (7), fill replaces it over border pieces
// field: GraphicWin +0x98 int32 flags            ; 0x80000 bit gates a fill path off for buttons; bit 0x20 = parent-relative rect (creation style set by Win_init; Win_flip_rect_2 adds the parent chain; GraphicWin_composite gates on it); high bit picks parent clip rect +0x13C (nonclient) vs +0x14C (client)
// field: GraphicWin +0x9C int32 flags2           ; bit0 = in-zlist/visible (Win_update_screen gate); bit1 guards vtbl+0x128 call; bit2 = live (Win_show no-op without it)
// field: GraphicWin +0xA8 Win* compositeProxy    ; Win_update_screen calls [this+0xA8]->vtbl+0x124; == self for top-level
// field: GraphicWin +0xC4 Win* parent
// field: GraphicWin +0x13C RECT rcNonclient      ; child clip source when +0x98 high bit set
// field: GraphicWin +0x14C RECT rcClient         ; child clip source (client children)
// field: GraphicWin +0x134 int32 min_w
// field: GraphicWin +0x138 int32 min_h
// field: GraphicWin +0x444 Buffer surface        ; embedded draw buffer
// field: GraphicWin +0x45c int32 text_justify    ; >=2 => always center
// field: GraphicWin +0x474 RECT clip             ; +0x474..0x480 draw rect
// field: GraphicWin +0x4c4 int32 client_w
// field: GraphicWin +0x4c8 int32 client_h        ; negative
// field: GraphicWin +0x9cc void* frame_corner_sprites ; +0x9cc..; NULL for option buttons
// field: BaseButton +0xa7c char* text
// field: BaseButton +0xa90 int32 glyph_count
// field: BaseButton +0xa94 int32 segment_count
// field: BaseButton +0xad4 void* state_sprites   ; +0xad4/ac8/aec/af8/b04/b10/b1c/b28/b34/b40 per-state frame/edge
// field: BasePop +0xa14 void* external_window     ; 0 = normal boxed popup (the patched branch); ==0 also = "titled" popup; copied from g_popup_def_ext_win by BasePop_ctor/reset, cleared by BasePop_start @0x601C71 (+0x6015C8) unless pops flags bit 0x100000, and by BasePop_exec_3 @0x60277C when the window is not visible
// field: BasePop +0x30a8 uint32 pops_flags        ; bit 0x100000 = keep external_window (diplomacy speech calls); bits 1/2/4 = dialog type 1/2/4 else 16; 0x400 = raw pad_x/pad_y (no x1.5)
extern void BasePop_set_external_window(struct BasePop* self, struct GraphicWin* win, int x, int y, int w, int h); // addr: 0x00605010  thinker  thiscall; unreferenced in this exe
// field: BasePop +0xa20 int32 req_w
// field: BasePop +0xa24 int32 req_h
// field: BasePop +0xa48 char* title_str            ; popup title string; 0 = untitled (title chain skipped in Popup_on_draw_background)
// field: BasePop +0x2118 Sprite art_sprite         ; embedded popup art bitmap (data@+0, w@+0x18=2130, h@+0x1c=2134); populated only for popups WITH an image
// field: BasePop +0x2144 Sprite* art_ptr           ; observed; the art Sprite* drawn by the [+0x3168] custom-draw path; NON-ZERO only for popups with a real image (Quit) / 0 for text-only (Planetfall) -> the reliable "has art" discriminator. [+0x3168] is set on ALL popups so is NOT.
// field: BasePop +0x3104 int art_ratio_num   popup art sprite scale numerator
// field: BasePop +0x3108 int art_ratio_den   popup art sprite scale denominator
// field: BasePop +0x3168 void* art_draw_fn   custom art draw (cdecl); 0 = BasePop_on_redraw draws the art itself
// field: BasePop +0x2c declared_width             ; in the dialog sub-struct
// field: BasePop +0x34 int32 text_indent          ; dialog sub-struct; list text-x = framebase + this; init = checkbox sprite width (~27) in FUN_0060ed10
// field: BasePop +0x60 int32 dialog_type          ; dialog sub-struct
// field: BasePop +0x64 int32 row_w                ; dialog sub-struct
// field: BasePop +0x68 int32 row_h                ; dialog sub-struct
// field: BasePop +0x70 Font* font                 ; dialog sub-struct (+0x70/74/78); the scaled 40px default
// field: BasePop +0x21fc int32 intrinsic_w        ; native list content width, res-independent (=660); box_w fallback when +0x222c==0
// field: BasePop +0x222c int32 intrinsic_w2       ; box_w source = max(native +0x21fc, g-scaled text)
// field: BasePop +0x30ac int32 popup_type_x10000  ; popup type * 10000 (0 flat / 5 slide / 2,6 ornate / 1000 hidden); consumers divide by 10000
// field: BasePop +0x21cc int32 dialog_x_override  ; >= 0 replaces the margin sum as the dialog-area left (Popup_on_draw_background @0x4060xx)
// field: BasePop +0x30bc int32 box_w
// field: BasePop +0x30c0 int32 box_h
// field: BasePop +0x30b0 int32 button_count        ; n of the button-width split
// field: BasePop +0x30cc int32 button_width        ; (box_w - 2*pad_x - (n-1)*pad_y) / n
// field: BasePop +0xa5c struct FlatButton btn_ok   id -1, label +0x3224 (default "OK"); BaseButton_init @0x602D66 unless flags 0x10000
// field: BasePop +0x15a8 struct FlatButton btn_cancel   id -2, label +0x3228 (default "Cancel"); BaseButton_init @0x60342B when flags 0x40
// field: BasePop +0x2160 int32 custom_button_count   the #button row loop count (BaseButton_init @0x6030DC, ids 1..)
// field: BasePop +0x20f8 struct FlatButton* custom_buttons[]   the row loop's operator-new'd buttons
// field: BasePop +0x30d0 int32 button_row_height  ; =20 (layout literal, not rendered bar height)
// field: BasePop +0x30d4 int32 content_h
// field: BasePop +0x30d8 int32 content_w
// field: BasePop +0x30e0 int32 pad_x
// field: BasePop +0x30e4 int32 pad_y              ; box_h gap below the dialog (and above it with body text); also the button row's x step
// field: BasePop +0x21b0 int32 margin_left_src    ; box content left margin (=10 list / 0x21 msg); set in Popup_calculate_dimensions; copied to +0x30f0
// field: BasePop +0x21b4 int32 margin_right_src   ; box content right margin (=0xc list / 0x43 msg); copied to +0x30f4
// field: BasePop +0x21b8 int32 header_reserve_src  ; =0x26(38) titled / 0x12 untitled; +9 for ornate types 2/6; set in Popup_calculate_dimensions; copied to +0x30e8
// field: BasePop +0x21c0 int32 pad_x_src           ; +0x30e0 = 3*src/2 above 1023px else src; zeroed by Popup_calculate_dimensions
// field: BasePop +0x21c4 int32 pad_y_src           ; =4 from Popup_calculate_dimensions; copied to +0x30e4
// field: BasePop +0x474 RECT window_rect           ; source of the backdrop, title-band and field rects in Popup_on_draw_background
// field: BasePop +0x21bc int32 margin_bottom_src  ; box content bottom margin (=0x12 list); copied to +0x30ec
// field: BasePop +0x30e8 int32 header_reserve       ; from +0x21b8; content_top(draw)=+0x30e8+0x30e0; box_h(+0x30c0) includes +0x30ec+0x30e8
// field: BasePop +0x30ec int32 footer_reserve       ; =+0x21bc; box_h += this (alongside +0x30e8)
// field: BasePop +0x30f0 int32 margin_left          ; =+0x21b0; box_w(+0x30bc) += +0x30f0+0x30f4; also offsets content origin X
// field: BasePop +0x30f4 int32 margin_right         ; =+0x21b4; box_w += this. (Box size DERIVES from these margins in BasePop_calculate_dimensions 0x603800 -> scale the +0x21bx sources to grow the box + inset content as a unit.)
// field: CRITICAL_SECTION +0x0 void* DebugInfo    ; size 0x18: +4 LockCount +8 RecursionCount +0xc OwningThread +0x10 LockSemaphore +0x14 SpinCount

// ==== PREFERENCES window (PrefWin; group prefwin_scale) ====
extern struct GraphicWin PrefWin_g;                                            // addr: 0x008578D8  observed  the PREFERENCES window (static); buf +0x444, outer rect +0x13C..+0x148
extern void PrefWin_build(void);                                               // addr: 0x0048D840  observed  runs once at desktop_init; 7 find_font calls 0x48D90A..0x48D962 (10/12x3/14x3), 7 Dialog_init_2 page calls 0x48DE26..0x48F0B1
extern void PrefWin_show(/*ecx*/ struct GraphicWin* self, int page);           // addr: 0x0048FA00  observed  thiscall; modal show; 5 Buffer_box_sprite chrome draws 0x48FB19..0x48FC01, slide_show @0x48FC66
extern void PrefWin_repaint_right(void);                                       // addr: 0x00491810  observed  right-panel repaint helper; rebuilds its rect from native globals (box_sprite @0x49184D)
extern void PrefWin_repaint_gamma(void);                                       // addr: 0x00491860  observed  gamma-frame repaint helper (box_sprite @0x4918B1)
extern void PrefWin_refresh(void);                                             // addr: 0x00491C00  observed  full-refresh; rebuilds both frames (box_sprite @0x491C42/0x491C8C), drives vtbl+0xF8 of children
extern int  Dialog_init_2(/*ecx*/ void* self, int x, int y, int w, int h, void* list); // addr: 0x00609300  thinker   thiscall; stores x/y/w/h at +0x24..+0x30
extern int  Dialog_init_3(/*ecx*/ void* self, RECT* rect, int len);              // addr: 0x00609470  thinker   thiscall RET 8; xs=R-L, h=B-T into +0x2c/+0x30, flags |= 3
extern int  Dialog_close(/*ecx*/ void* self);                                  // addr: 0x00608F50  thinker   thiscall; resets the field defaults (gap +0x44 = g_dialog_default_gap)
extern int  g_dialog_default_gap;                                              // addr: 0x0069709C  observed  Dialog default row gap (6)
extern int  Dialog_ctor(/*ecx*/ struct Dialog* self);                          // addr: 0x00608C10  thinker  thiscall; field defaults: row_stride +0x48 = -1, row_gap +0x44 = g_dialog_default_gap, text_indent +0x34 = g_dialog_default_indent
extern int  g_dialog_default_indent;                                           // addr: 0x009B8EB8  observed  Dialog default text indent (Dialog_ctor -> +0x34)
extern DWORD ListBox_ctor(/*ecx*/ struct ListBox* self, int is_dialogs);       // addr: 0x00609DB0  thinker  thiscall RET 4; vbtable 0x670584: GraphicWin part +0x48, Dialog part +0xA60
extern int  FUN_0060e800_type1_attach(/*ecx*/ void* iface, void* win, int x, int y, int flags); // addr: 0x0060E800  observed  thiscall; type-1 element attach (all PrefWin pages funnel here); baked prefwin entry detour
extern void* ScrollBar_vtbl;                                                   // addr: 0x00669D58  observed  ScrollBar vtable: +0x30 draw slot @0x669D88 = ScrollBar_draw (repointed by prefwin_scale), +0x34 on_resize, +0x64 on_key, +0xA4 chevron repeat, +0xB0 chevron, +0x138 App_on_key_message
extern struct Dialog PrefWin_page_dlg_1;                                       // addr: 0x0085DC80  observed  page Dialog statics, init (256,10,457,h) via the 7 PrefWin_build sites
extern struct Dialog PrefWin_page_dlg_2;                                       // addr: 0x0085E7A8  observed
extern struct Dialog PrefWin_page_dlg_3;                                       // addr: 0x0085F2D0  observed
extern struct Dialog PrefWin_page_dlg_4;                                       // addr: 0x0085FDF8  observed
extern struct Dialog PrefWin_page_dlg_5;                                       // addr: 0x00860920  observed
extern struct Dialog PrefWin_page_dlg_6;                                       // addr: 0x00861448  observed
extern struct Dialog PrefWin_page_dlg_7;                                       // addr: 0x00861F70  observed
extern struct FlatButton PrefWin_btn_prefs;                                    // addr: 0x00858338  observed  "Preferences" (left col; 15 buttons total, cluster [0x858338,0x872140])
extern struct FlatButton PrefWin_btn_adv;                                      // addr: 0x00858E84  observed  "Adv. Preferences"
extern struct FlatButton PrefWin_btn_warn;                                     // addr: 0x008599D0  observed  "Warning Preferences"
extern struct FlatButton PrefWin_btn_auto;                                     // addr: 0x0085A51C  observed  "Automation Preferences"
extern struct FlatButton PrefWin_btn_av;                                       // addr: 0x0085B068  observed  "Audio/Visual Preferences"
extern struct FlatButton PrefWin_btn_map;                                      // addr: 0x0085BBB4  observed  "Map Preferences"
extern struct FlatButton PrefWin_btn_gamma;                                    // addr: 0x0085C700  observed  "Gamma Correction"
extern struct ScrollBar PrefWin_slider_main;                                   // addr: 0x00862064  observed  Main volume (328x20 native; arrow/thumb children parented here)
extern struct ScrollBar PrefWin_slider_voice;                                  // addr: 0x008641B0  observed  Voice volume
extern struct ScrollBar PrefWin_slider_sfx;                                    // addr: 0x008662FC  observed  SFX volume
extern struct ScrollBar PrefWin_slider_music;                                  // addr: 0x00868448  observed  Music volume
extern struct FlatButton PrefWin_btn_main_off;                                 // addr: 0x0086C6E0  observed  "Main Off" (120x20 toggle)
extern struct FlatButton PrefWin_btn_sfx_off;                                  // addr: 0x0086D22C  observed  "SFX Off"
extern struct FlatButton PrefWin_btn_voice_off;                                // addr: 0x0086DD78  observed  "Voice Off"
extern struct FlatButton PrefWin_btn_music_off;                                // addr: 0x0086E8C4  observed  "Music Off"
extern struct FlatButton PrefWin_btn_restore;                                  // addr: 0x0086FF5C  observed  "Restore Defaults"
extern struct FlatButton PrefWin_btn_cancel;                                   // addr: 0x00870AA8  observed  "Cancel"
extern struct FlatButton PrefWin_btn_ok;                                       // addr: 0x008715F4  observed  "OK"
extern struct FlatButton PrefWin_btn_more;                                     // addr: 0x00872140  observed  "More"
extern void PrefWin_ctor(/*ecx*/ struct GraphicWin* self);                     // addr: 0x004921E0  observed  thiscall; 16 FlatButton_ctor + 7 page ctor + 5 ScrollBar_ctor; installs vtable
extern void* PrefWin_vtbl[90];                                                 // addr: 0x0066D424  observed  slots: +0x30 on_redraw=PrefWin_refresh, +0x64 on_key=0x48FCD0, +0xB0 on_command=0x491400, +0xB8 group_sel_changed=0x48FF60, +0xC4 on_slider_changed=0x491380
extern int  PrefWin_on_key();                                                  // addr: 0x0048FCD0  observed  thiscall(a2,key) vtbl+0x64; 0xD Enter=commit-close, 0x1B ESC=cancel-close, 0x26/0x28 arrows cycle tabs 0..5
extern void PrefWin_on_command(/*ecx*/ void* self, int id);                    // addr: 0x00491400  observed  thiscall vtbl+0xB0; switch: 6 gamma-apply, 0x5A restore-defaults, 0x5C OK, 0x5B cancel, 0x5E warnings-page2 toggle; default -> refresh
extern void PrefWin_group_sel_changed(/*ecx*/ void* self, int gid, int oldid, int newid); // addr: 0x0048FF60  observed  thiscall vtbl+0xB8; stores prev (only 0..5) + cur tab, chains vtbl+0xB0(new)
extern void PrefWin_on_slider_changed(/*ecx*/ void* self, int id, int value);  // addr: 0x00491380  observed  thiscall vtbl+0xC4; 0x50..0x53 apply volumes live
extern void PrefWin_hide_prev_page(/*ecx*/ void* self);                        // addr: 0x0048FFB0  observed  thiscall; switch [+0xA18] prev tab -> hide page + widgets (case 4 = audio: 4 sliders + 4 labels)
extern void PrefWin_show_cur_page(/*ecx*/ void* self);                         // addr: 0x00490140  observed  thiscall; switch [+0xA14] cur tab -> show page + widgets; NO case >6 (custom tab ids show nothing)
extern void PrefWin_commit_close(/*ecx*/ void* self);                          // addr: 0x0048FDD0  observed  thiscall; if [+0xA5C] merge pref bits + prefs_use/prefs_save + prefs_put_2 x4 volumes; draw_map(1) + slide_hide + hide
// field: PrefWin +0xA14 int cur_tab     0..5 tabs; 6 = warnings page 2; button id stored raw on custom tabs
// field: PrefWin +0xA18 int prev_tab    only ever 0..5 (group_sel_changed clamps)
// field: PrefWin +0xA1C int skip_prev_store   set by the key tab-cycle before ButtonGroup_select
// field: PrefWin +0xA5C int ok_flag     commit-on-close ([0x297]; OK/Enter set it)
extern struct ButtonGroup PrefWin_tab_group;                                   // addr: 0x008577F0  observed  the 6-tab radio group (id 0x5D); member cap 0x20
extern struct FlatButton PrefWin_btn0;                                         // addr: 0x00858338  observed  first stock tab FlatButton (Game Preferences)
extern int  g_prefwin_tab_x;                                                   // addr: 0x0085788C  observed  tab column x (native units)
extern int  g_prefwin_tab_y0;                                                  // addr: 0x00857890  observed  tab column y0; rows at +0x16 pitch
extern int  g_prefwin_tab_w;                                                   // addr: 0x00857894  observed  tab button width
extern int  g_prefwin_tab_h;                                                   // addr: 0x00686B88  observed  tab button height
extern int  g_prefwin_label_x;                                                 // addr: 0x008578B4  observed  slider-row label x
extern int  g_prefwin_label_y0;                                                // addr: 0x008578BC  observed  slider-row label y0 (pre bot-shift)
extern int  g_prefwin_label_w;                                                 // addr: 0x00686B8C  observed  slider-row label width
extern int  g_prefwin_label_h;                                                 // addr: 0x00686B90  observed  slider-row label height
extern int  g_prefwin_slider_x;                                                // addr: 0x008578CC  observed  audio-page slider x
extern int  g_prefwin_slider_y0;                                               // addr: 0x008578D0  observed  audio-page slider y0
extern int  g_prefwin_slider_w;                                                // addr: 0x008578B8  observed  audio-page slider width
extern int  g_prefwin_bot_shift;                                               // addr: 0x00872CA8  observed  SW==800 bottom-stack y shift
extern int  g_prefwin_frame_x;                                                 // addr: 0x008577D8  observed  audio slider-area frame rect x
extern int  g_prefwin_frame_y;                                                 // addr: 0x008577DC  observed  audio slider-area frame rect y (pre bot-shift)
extern int  g_prefwin_frame_h;                                                 // addr: 0x008577E0  observed  audio slider-area frame rect h
extern int  g_prefwin_frame_w;                                                 // addr: 0x008577E4  observed  audio slider-area frame rect w
extern void ButtonGroup_init(/*ecx*/ void* self, int gid, int flags);          // addr: 0x0062B810  observed  thiscall
extern void ButtonGroup_add(/*ecx*/ void* self, void* btn);                    // addr: 0x0062B850  observed  thiscall; appends member, sets btn+0xAA8 group ptr
extern int  ButtonGroup_select(/*ecx*/ void* self, int id);                    // addr: 0x0062B8A0  observed  thiscall; unpress old/press new, notifies owner vtbl+0xBC(old,new) then vtbl+0xB8(gid,old,new)
// field: FlatButton +0xA78 int button_id     ; +0xAA8 ButtonGroup* group
// field: FlatButton +0x970 struct Font* label_font   seeded native at init; thunk_pref_show rescales the 15 stock PrefWin ones per show
extern void ScrollBar_ctor(/*ecx*/ struct ScrollBar* self);                    // addr: 0x006051D0  observed  thiscall; GraphicWin + 2 arrow FlatButtons; vtable 0x669D58; size 0x214C
extern int  ScrollBar_init(/*ecx*/ struct ScrollBar* self, int x, int y, int w, void* parent, int id); // addr: 0x006058D0  observed  thiscall; h=g_scrollbar_w; -> ScrollBar_init_inner
extern int  ScrollBar_init_v(/*ecx*/ struct ScrollBar* self, int x, int y, int h, void* parent, int id); // addr: 0x00605910  observed  thiscall RET 0x14; vertical: w=g_scrollbar_w (load @0x605938); -> ScrollBar_init_inner; Win V bar caller @0x5EC427
extern int  ScrollBar_init_inner(/*ecx*/ struct ScrollBar* self, int x, int y, int w, int h, void* parent, int id, int flags); // addr: 0x006054D0  observed  thiscall; GraphicWin_init + 2 arrow BaseButton_init(parent=self)
extern void ScrollBar_set_range(/*ecx*/ struct ScrollBar* self, int mn, int mx); // addr: 0x006059B0  observed  thiscall
extern void ScrollBar_set_pos(/*ecx*/ struct ScrollBar* self, int pos);        // addr: 0x00605D20  observed  thiscall; clamps to range; no parent notify (user drag notifies parent vtbl+0xC4(id,value))
// field: ScrollBar +0xA20 int range_min  ; +0xA24 max ; +0xA28 inverted ; +0xA2C value
extern int  prefs_get_2(const char* name, int def, int a3);                    // addr: 0x0059DB40  thinker   cdecl
extern void prefs_put_2(const char* name, int value, int a3);                  // addr: 0x0059E530  thinker   cdecl
extern void prefs_save(int a1);                                                // addr: 0x0059E5D0  thinker   cdecl
extern void prefs_use(void);                                                   // addr: 0x0059E950  thinker   cdecl
extern void draw_map(int a1);                                                  // addr: 0x0046B190  thinker   cdecl; full map redraw
extern void BaseButton_set_name(/*ecx*/ void* self, const char* name);         // addr: 0x006074E0  thinker   thiscall

// ==== Scrollbar RAIL slide helpers (console right-edge rail + embedded ScrollBar) ====
extern void rail_slide_in(void* win, void* sb);                                // addr: 0x0045DEA0  observed  cdecl RETN; synthesizes the 47px right rail strip (console_x art: 32px rail + 15px wall) into a 47xH buffer, animates open, bakes to win canvas at clientW-47, then sb resize(0x18, railH-0xA)+move(clientW-0x2B, 0x15)+show
extern void rail_slide_out(void* win, void* sb);                               // addr: 0x0045E540  observed  cdecl; captures the strip from the canvas, animates closed, fills strip key-9, bakes closed wall, hides sb
extern int  popup_sb_create(void* win);                                        // addr: 0x00406260  observed  popup-family sb creator: same tile-quantized height law + init_inner(clientW-0x2B, 0x15, 0x18, h) at popup sb +0x3230
extern void popup_sb_remove(void* win);                                        // addr: 0x00406330  observed  popup-family sb remover
extern int  g_rail_vstep;                                                      // addr: 0x007D3924  observed  rail vertical slide step (written by rail_slide_in, read by rail_slide_out)
extern int  g_rail_hstep;                                                      // addr: 0x007D38B0  observed  rail horizontal slide step (4 SP / 8 MP)
extern int  g_anim_frame_ms;                                                   // addr: 0x00691AF8  observed  static 20; slide loops wait >>1 = 10ms/frame
// field: MainWin +0x216F4 Sprite railTopCap    32x26 (VA 0x7CFF14; console_x_A/x2_A.pcx atlas (1,0x117))
// field: MainWin +0x21720 Sprite railMidTile   32x34 (VA 0x7CFF40; atlas (1,0x132); rail h quantizes to caps+N*34)
// field: MainWin +0x2174C Sprite railBotCap    32x25 (VA 0x7CFF6C; atlas (1,0x155))
// field: MainWin +0x21778 Sprite railFiller    32x34 (VA 0x7CFF98; atlas (1,0x16F); tiles below the rail to the window bottom)
// field: Sprite +0x08 u8 transparent_index   +0x18 int width   +0x1C int height   (Buffer_tile_2 reads +0x18/+0x1C)
// field: Popup +0x3230 ScrollBar sb   (popup_sb_create init_inner(clientW-0x2B,0x15,0x18,h) parent=popup id=-1 flags=1, created hidden; rail_slide_in(popup,&sb) from Popup_show 0x404A08/0x404A63 when [+0x2350]==2 && items>[+0x21EC], from popup_sb_create 0x406312 when already visible; rail_slide_out from Popup_hide 0x404AE2 / popup_sb_remove 0x40636D)
extern struct Scroll g_prodpicker_sb;                                          // addr: 0x006AF164  observed  ProdPicker +0x7120, size 0x214C; created hidden by ProdPicker_exec 0x4949DE, re-geometried + shown by rail_slide_in
extern struct FlatButton g_prodpicker_sb_arrow_up;                             // addr: 0x006AFC10  observed  g_prodpicker_sb +0xAAC, stride 0xB4C
extern struct FlatButton g_prodpicker_sb_arrow_dn;                             // addr: 0x006B075C  observed  g_prodpicker_sb +0x15F8
// field: Scroll +0xA60 int btn   element square = min(w,h); drives BOTH arrow buttons and the thumb, so the widget self-adapts once its rect scales

// ==== Planetary Council session screen (CouncilWin 0x6FEC80) ====
extern struct CouncilWindow* CouncilWin;                              // addr: 0x006FEC80  thinker   static window object; FlatButton[6] @+0xD94 = [0x6FFA14, 0x703DDC)
extern void CouncilWin_ctor(int* self);                               // addr: 0x00428620  observed  fastcall; GraphicWin_ctor + Spot + 6 Font_ctor + FlatButton[6] array-ctor @+0xD94 stride 0xB4C
extern void CouncilWin_dtor(int* self);                               // addr: 0x00428550  observed  thiscall
extern void CouncilWin_exec(int* self, int proposal, int a3);         // addr: 0x00427230  observed  thiscall; seed table +0xBA4..+0xD10 + 6 Font_init + GraphicWin_init 812x min(395,SH-strip) @0x427A1D + modal loop
extern void CouncilWin_repaint(void* self);                           // addr: 0x00426AA0  observed  fastcall(ecx); backdrop d690/d5a0 + proposal panel + 7 columns + ELECTED banner
extern void CouncilWin_draw_column(void* self, int faction);          // addr: 0x00425DB0  observed  thiscall RET 4; frame d528 + portrait sd2 1:1 + 2 name lines + logo + vote chip (da28/d9d8/da00/d528) + votes label
extern void CouncilWin_draw_proposal(void* self);                     // addr: 0x00426470  observed  fastcall(ecx); console propbox: d618 header + d528 body + tally rows
extern void CouncilWin_on_hover(int self, int a2, int a3);            // addr: 0x00426EE0  observed  thiscall; Spot_check -> +0xA34 hover, redraws changed columns
extern void CouncilWin_show_hide(int self, int show);                 // addr: 0x00426FA0  observed  thiscall RET 4; ecx=self+0xA14; slide_show E8 @0x426FF6, slide_hide E8 @0x427039
extern void CouncilWin_show(int* self);                                // addr: 0x00427130  observed  thiscall RET 4; vtbl+0x4; SubInterface_set_iface_mode(self+0xA14) if hidden
extern void CouncilWin_vote_result(int* self, int faction, int vote); // addr: 0x00424720  observed  thiscall; writes +0xA54[f], re-tallies, redraws
extern int  CouncilWin_tally(int* self, int commit);                  // addr: 0x00424410  observed  thiscall; sets +0xA24/+0xA20 outcome
extern void call_council(int faction);                                // addr: 0x0052C880  thinker   cdecl; propose picker = stack Popup, one Dialogs_item per motion
// field: CouncilWin +0x444  struct Buffer canvas
// field: CouncilWin +0xA18  int spot_count (7)
// field: CouncilWin +0xA1C  int proposal
// field: CouncilWin +0xA20  int winner
// field: CouncilWin +0xA24  int done_state (0 live / 1 passed / -1 failed / -2 tie)
// field: CouncilWin +0xA28  int governor_snapshot
// field: CouncilWin +0xA34  int hover_faction (-1 none)
// field: CouncilWin +0xA44  int human_mask
// field: CouncilWin +0xA54  int vote_cast[8]     (council_get_vote; -1..-5 = abstain family, >0 = faction)
// field: CouncilWin +0xA74  int vote_weight[8]   (council_votes)
// field: CouncilWin +0xAB4  struct Font fonts[6]  stride 0x28: ab4=14 adc=14 b04=12(+pad5) b2c=12 b54=14 b7c=20 (Arial Narrow, style 1)
// field: CouncilWin +0xBA4  RECT banner_rect     seed (245,355,538,378)
// field: CouncilWin +0xBB4  RECT propbox_rect    console rect [0x7AF5C0] inset 4
// field: CouncilWin +0xBC4  int col_span_l (30); +0xBC8 count 7; +0xBCC span_r (750); +0xBD0 (27)
// field: CouncilWin +0xBF4  RECT col_outer[7] stride 0x20 (governor-seated layout, tall center slot3 330,29,450,352), interleaved col_inner[7] @+0xC04 (flat 29..311, w 98, L 32+103c)
// field: CouncilWin +0xCD4  RECT btn_thirds[3] stride 0x10; +0xD04 btn_full (console row, top = boxB-0x17)
// field: CouncilWin +0xD14  Sprite* logo_pair[8][2]     (idx 2f = hover-bright, 2f+1 = dim; canvas 86x72)
// field: CouncilWin +0xD54  Sprite* portrait_pair[8][2] (idx 2f = 96x115, 2f+1 = governor 118x144)
// field: CouncilWin +0xD94  struct FlatButton buttons[6] stride 0xB4C (console VOTE/option row; BaseButton_init ids 1-5)

// ==== Social Engineering screen (SocialWin 0x8A6270) ====
extern void* SocialWin;                                               // addr: 0x008A6270  thinker   GraphicWin subclass; vtable 0x66DAA4
extern struct CSocialParam* SocialParam;                              // addr: 0x00946580  thinker   CSocialParam[?] 104B ea
extern int  society_avail(int category, int model, int faction);     // addr: 0x005B4730  thinker   cdecl; nonzero = the model is selectable
extern struct CSocialField* SocialField;                              // addr: 0x0094B000  thinker   CSocialField[4] 212B ea; +0x04 soc_preq_tech[4] locks buttonless rows
extern void social_set(int faction);                                  // addr: 0x005B4600  thinker   cdecl
extern void social_select(int faction);                               // addr: 0x005B5620  thinker   cdecl; opens SE screen -> SocialWin_build
extern void help_social(int a1);                                      // addr: 0x0044CA40  thinker   cdecl
extern void help_topic(int category, int item);                          // addr: 0x0044CB60  thinker   cdecl; -> DatalinkWin_open(cat,item)
extern void SocialWin_ctor(int* self);                                // addr: 0x004AE9E0  observed  thiscall
extern void SocialWin_build(int* self, int faction);                  // addr: 0x004B2740  observed  thiscall RET 4; MODAL (tail call [vtbl+0xE4] Win_set_modal @0x4B3C4A, returns on close); layout+show: writes ALL rect tables +0x1EFD0..+0x1F2EC, GraphicWin_init((SW-0x321)/2, SH-strip-0x162, 0x341, 0x162) @0x4B32C4..FF
extern void SocialWin_close(void* self);                              // addr: 0x004B26D0  observed  fastcall
extern void SocialWin_model_reset(void* self);                        // addr: 0x004AECE0  observed  fastcall; ButtonGroup sync + redraw
extern void SocialWin_repaint(void* self);                            // addr: 0x004B19A0  observed  fastcall(ecx); vtbl+0x30 master painter: MainWin_tile_panels(1) + 2 union frames + all panel painters
extern void SocialWin_draw_society_panel(void* self);                 // addr: 0x004AF1E0  observed  fastcall; SOCIETY outer frame + title
extern void SocialWin_draw_band(void* self, int band);                // addr: 0x004AF310  observed  thiscall RET 4; band 0..3 header+options+effect icons; locked-row placeholder branch
extern void SocialWin_draw_faction_box(void* self);                   // addr: 0x004AF8C0  observed  fastcall; SPARTANS box
extern void SocialWin_draw_center_console(void* self);                // addr: 0x004AFB60  observed  fastcall; SOCIAL ENGINEERING title + NET INCOME (ScreenWidth==800 layout branch)
extern void SocialWin_draw_effects_text(void* self);                  // addr: 0x004B0410  observed  fastcall; SOCIAL EFFECTS wrapped text -> MainWin buf 0x7AEC64
extern void SocialWin_draw_slider_econ(void* self);                   // addr: 0x004B08A0  observed  fastcall; Buffer_tile 14x14 fill/empty textures
extern void SocialWin_draw_slider_labs(void* self);                   // addr: 0x004B0B00  observed  fastcall
extern void SocialWin_draw_slider_psych(void* self);                  // addr: 0x004B0D50  observed  fastcall
extern void SocialWin_draw_hover_panel(void* self);                   // addr: 0x004B1080  observed  fastcall; hover-effects icon rows -> MainWin buf (inline rebuild path)
extern void SocialWin_draw_society_row(int* self, void* btn, char* label, int id); // addr: 0x004B17A0  observed  thiscall; vtbl+0x14, fires for ALL 35 FlatButtons ids 0x0..0x1C (options/society/OK-row), rect from btn+0x474
extern void SocialWin_redistribute(int* self);                        // addr: 0x004B1FF0  observed  thiscall; arrow-click allocation math
extern void SocialWin_on_arrow(int* self);                            // addr: 0x004B2470  observed  thiscall; ids 0x1D..0x22 -> +-1 econ/labs/psych + full repaint
extern void SocialWin_on_command(int* self);                          // addr: 0x004B1E00  observed  OK(0x10)/RESET(0x1B)/CANCEL(0x1C) dispatch
extern void SocialWin_on_option_click(int* self);                     // addr: 0x004B1CE0  observed  vtbl+0xBC option/society click
extern void SocialWin_on_mouse_move(int* self);                       // addr: 0x004B1EC0  observed  vtbl+0x44 hover tracking
extern void SocialWin_on_mouse_leave(int* self);                      // addr: 0x004B1FC0  observed  vtbl+0x48
extern void SocialWin_hover_refresh(int* self);                       // addr: 0x004B1D70  observed  vtbl+0xA0 -> partial redraws 0x4B1080/0x4B0410
extern void SocialWin_show_hide(int* self, int show);                 // addr: 0x004B2120  observed  thiscall; slide_show E8 @0x4B2192 / slide_hide E8 @0x4B21B3 of window -0xA14 (push 0/push esi)
// field: SocialWin +0x2C38 int alloc_a[3]        allocation triple {10-x-y, x, y} copy A, seeded by SocialWin_build from Faction+0x20CC*f (+0x96CD04/+0x96CD08 at f=0); +0x2C44 copy B; +0x2C50 copy C (+0x2BB0..+0x2C60 = scalars, NOT sprites)
// field: SocialWin +0x2C60 struct Sprite digits[10]   13x13 socwin (0x115+0xE*i, 0x6F|0x7D), re-extracted every build; +0x2C70 = digits[0].blit_w (the painter's digit-w alias)
// field: SocialWin +0x2E18 struct Sprite icons[90]    26x26 effect icons 10 types x 9 variants (socwin grid from (1,1) step 0x1B), extracted once (guard = icons[0].data +0x2E1C)
// field: SocialWin +0x3D90 struct Sprite locks[2]     24x14 socwin (0xF5,1)/(0xF5,0x10)
// field: SocialWin +0x3DE8 struct Sprite arrows[6]    20x20 socwin pairs (0x13B,y)/(0x150,y) y=1 step 0x15
// field: SocialWin +0x444   struct Buffer canvas (modal window buffer)
// field: SocialWin +0x474   RECT win_rect_local  (0,0,w,h) window-local; screen rect at +0x13C (GraphicWin base)
// field: SocialWin +0xA2C   int hover_opt        (-1 none, -2 current-society)
// field: SocialWin +0xA30   int hover_soc_row
// field: SocialWin +0xCF4   int faction
// field: SocialWin +0xCF8   int chosen_soc[4]
// field: SocialWin +0xD08   int effect_vals[11]
// field: SocialWin +0xD6C   struct lock_toggle[3] stride 0xA2C  parent MainWin
// field: SocialWin +0x2C60  struct Sprite sprites10[10] stride 0x2C
// field: SocialWin +0x2E18  struct Sprite effect_icons[90] 10 types x 9 variants 26x26 (socwin.pcx grid)
// field: SocialWin +0x2E30  int icon_gap          ALIAS: effect-icon sprite[0] +0x18 canvas w (26)
// field: SocialWin +0x2E34  int row_h             ALIAS: effect-icon sprite[0] +0x1C canvas h (26)
// field: SocialWin +0x2C70  int big_icon_w        ALIAS: digit sprite[4] +0x10 blit w (7)
// field: SocialWin +0x3DA8  int slider_bar_x_inset ALIAS: lock sprite[0] +0x18 canvas w (24)
// field: SocialWin +0x3DAC  int slider_bar_h      ALIAS: lock sprite[0] +0x1C canvas h (14)
// field: SocialWin +0x3EF0  struct Buffer slider_tiles[6] stride 0x588  14x14 fill/empty pairs econ/labs/psych
// field: SocialWin +0x6020  struct FlatButton buttons[35] stride 0xB4C  16 option + 10 society(0x11..0x1A) + OK/RESET/CANCEL(0x10/0x1B/0x1C) + 6 arrows(0x1D..0x22 parent MainWin)
// field: SocialWin +0x1EE68 struct Font fonts[9] stride 0x28  F0/F1 hud14b F2/F3 AN14b F4 hud12 F5 hud11b F6 hud11 F8 AN14b
// field: SocialWin +0x1EFD0 RECT lock_rects[3]
// field: SocialWin +0x1F000 RECT arrow_rects[6]
// field: SocialWin +0x1F060 RECT society_outer    seed {0x271,4,0x306,0xFA}
// field: SocialWin +0x1F070 RECT society_rows[10] seed y0=0x1D step 0x16 h 0x14
// field: SocialWin +0x1F110 RECT band_rects[4]    seed {0x1A, 4/0x4D/0x96/0xDF, 0x26E, +0x46}
// field: SocialWin +0x1F150 RECT option_rects[16] seed x {0x1D,0xB1,0x145,0x1D9} w 0x92, y {0x1D,0x66,0xAF,0xF8} h 0x14
// field: SocialWin +0x1F250 RECT fx_text_box      console-left rect [0x7AF5B0] inset 4
// field: SocialWin +0x1F260 RECT slider_econ      console strip cols; +0x1F270 slider_labs, +0x1F280 slider_psych
// field: SocialWin +0x1F290 RECT hover_box
// field: SocialWin +0x1F2A0 RECT faction_box      seed {0x271,0xFD,0x306,0x12D}
// field: SocialWin +0x1F2B0 RECT btn_ok           seed {0x1E4,0x13A,0x286,0x14E}; +0x1F2C0 btn_reset, +0x1F2D0 btn_cancel
// field: SocialWin +0x1F2E0 RECT center_box       console-center rect [0x7AF5C0] inset 4

// ============================================================================
// ==== TECH BREAKTHROUGH window (NetTechWin; single-player + multiplayer) ====
// ============================================================================
extern struct NetTechWindow NetTechWin_g;                             // addr: 0x00811E40  thinker   GraphicWin 550x600; vtbl 0x66CE5C
extern void NetTechWin_exec(/*ecx*/ struct NetTechWindow* self, int tech_id, int flag); // addr: 0x00483F90  observed  thiscall RET 8; rect cascade + GraphicWin_init_2 @0x4842E7 + modal loop @0x48478D; caller tech_achieved 0x5BBA22
extern void NetTechWin_draw(/*ecx*/ struct NetTechWindow* self);      // addr: 0x00483950  observed  fastcall; vtbl+0x30 painter; 14 Buffer_box_sprite + icon Sprite_draw_mono_scaled @0x483E60
extern void NetTechWin_list_add_line(const char* text);               // addr: 0x00483920  observed  cdecl; help_tech_info callback -> TextScroll[g_nettech_list_idx]
extern void NetTechWin_on_button(/*ecx*/ struct NetTechWindow* self, int id); // addr: 0x00483E80  observed  thiscall RET 4; OK -> vtbl+0xE8 modal exit
extern void NetTechWin_on_group_changed();                            // addr: 0x00483EB0  observed  thiscall; group id 1 / 2 -> quote TextScroll text reload
extern void NetTechWin_dtor_body(/*ecx*/ struct NetTechWindow* self); // addr: 0x00484810  observed  fastcall
extern void* NetTechWin_vtbl;                                         // addr: 0x0066CE5C  observed  +0x30 draw, +0xB0 on_button, +0xBC on_group_changed
extern int  g_nettech_datalinks_req;                                  // addr: 0x00686960  observed  packed datalinks id requested from a list link; -1 none
extern int  g_nettech_list_idx;                                       // addr: 0x00686964  observed  list TextScroll index 0..3 during help_tech_info
// field: NetTechWin +0xA14  RECT win           {0,0,0x226,0x258}
// field: NetTechWin +0xA24  RECT content       d5a0 frame
// field: NetTechWin +0xA34  RECT header        d528
// field: NetTechWin +0xA44  RECT icon_panel    d528; tech name + icon
// field: NetTechWin +0xA54  RECT list[4]       d528; TL, TR, BL, BR
// field: NetTechWin +0xA94  RECT caption[4]    d618; TL, TR, BL, BR
// field: NetTechWin +0xAD4  RECT quote         d528
// field: NetTechWin +0xAE4  RECT quote_text    quote with R = btn1.L - 4
// field: NetTechWin +0xAF4  RECT ok            OK button; ring = -/+3 d5a0
// field: NetTechWin +0xB04  RECT btn1          28x34 icon button id 1
// field: NetTechWin +0xB14  RECT btn2          28x34 icon button id 2
// field: NetTechWin +0xB24  int tech_id
// field: NetTechWin +0xB28  int flag           >0 selects the alternate header label
// field: NetTechWin +0xB2C  struct FlatButton btn[3]   stride 0xB4C; OK, id 1, id 2
// field: NetTechWin +0x2D10 struct ButtonGroup group   ids 1, 2
// field: NetTechWin +0x2DA4 struct TextScroll list_ts[4]   stride 0x2BA0
// field: NetTechWin +0xDC24 struct TextScroll quote_ts

// ============================================================================
// ==== SELECT RESEARCH GOAL tech-pick screen (stack-local TechWin in tech_pick) ====
// ============================================================================
extern int  tech_pick(int faction_id, int flag, int other_faction_id, const char* label); // addr: 0x005BEB70  thinker   cdecl; stack TechWin @[ebp-0xC68] (0xC5C B); callers tech_selection 0x5BE4AC / Console_set_tech 0x515080 / steal_tech 0x50C398
extern struct CTech Tech[];                                           // addr: 0x0094F358  thinker  stride 0x2C; +4 name, +8 short name, +0x24 / +0x28 prerequisites
extern int  tech_recurse(int tech_id, int level);                     // addr: 0x005B9F90  thinker  cdecl; tech level = max over the prerequisite chain
extern int  tech_category(int tech_id);                               // addr: 0x005B9FE0  thinker  cdecl; 0..3
extern int  tech_rate(int faction_id);                                // addr: 0x005BE6B0  thinker  cdecl; research cost of the next tech
extern void* TechWin_vtbl;                                            // addr: 0x0066CFCC  observed  +0x44 on_mouse_move +0x4C on_lclick +0x58 on_rclick +0x64 on_key +0xE4 Win_set_modal +0xF8 GraphicWin_redraw; +0x30 = stub 0x404280 (paints itself)
extern void TechWin_ctor(int* self);                                  // addr: 0x00484AC0  observed  thiscall(ecx); GraphicWin_ctor + 4 Font_ctor (+0xBBC/+0xBE4/+0xC0C/+0xC34); installs vtbl 0x66CFCC, canvas vtbl 0x66CFC4
extern void TechWin_close(int* self);                                 // addr: 0x00484B60  observed  fastcall(ecx); zero cols/rows/hover, tail-jmp GraphicWin_close
extern int  TechWin_exec(int* self, int faction, int flag, int other, const char* label); // addr: 0x00486510  observed  thiscall RET 0x10; candidate scan + Font_init x4 + grid law + GraphicWin_init @0x487D5A + Win_center + backdrop/caption + cell loop @0x487E85 + modal vtbl+0xE4 @0x487ED2; returns tech id / -1
extern int  TechWin_draw_cell(int* self, int idx, int hilite);        // addr: 0x004863F0  observed  thiscall RET 8; rect {col*(cw+1)+1, row*(ch+1)+0x1E, +cw, +ch} clip, R/B-3, Buffer_box_sprite d528 (d578 hilite) @0x4864D8, content @0x4864EF
extern int  TechWin_draw_cell_content(int* self, int tech, RECT* r, int hilite); // addr: 0x00484C60  observed  thiscall RET 0xC; name (find_font 20/18/12) + category line + icon Sprite_draw_mono_2 @0x4851D9 + TECHSHORTS quote Buffer_write_strings @0x4853F5 + unlock lines
extern void TechWin_write_unlock_line(int* self, const char* str);    // addr: 0x00484B80  observed  thiscall RET 4; bottom-anchored: +0xA44 -= wrap_height(str, W-2); wrap_cent_4(str, L+1, +0xA44, W-2); markup {}=bold []=italic
extern void TechWin_on_mouse_move(int* self, int x, int y);           // addr: 0x00485FC0  observed  thiscall RET 8; vtbl+0x44; y-=0x1D; idx=(y/(ch+1))*cols+x/(cw+1); redraw new+old via draw_cell
extern void TechWin_on_lclick(int* self, int x, int y);               // addr: 0x004860B0  observed  thiscall; vtbl+0x4C; hover valid -> clear g_sb_track_win + vtbl+0xE8 modal exit
extern void TechWin_on_rclick(int* self, int x, int y);               // addr: 0x00486110  observed  thiscall; vtbl+0x58; hide, do_all_draws, FUN_00429180(0xE, tech), re-exec vtbl+0xE4
extern int  TechWin_on_key(int* self, int a2, int key);               // addr: 0x00486170  observed  thiscall; vtbl+0x64; arrows/tab/numpad move hover, Enter/Space select, F1/'H' help_any
extern struct Sprite* g_tech_icon_sprites;                            // addr: 0x00759E28  observed  Sprite[] stride 0x2C indexed by tech id; 215x215 mono art drawn via Sprite_draw_mono_2 with SCALE_NUM_G=(16+s)/16
extern int  g_tech_category_color[];                                  // addr: 0x008C6DE4  observed  dword pairs stride 8 indexed by tech_category; icon color
extern int  g_tech_category_label[];                                  // addr: 0x0094B4A4  observed  dword pairs stride 8 indexed by tech_category; Strings_get id for "EXPLORE"/"BUILD"/...
// field: Win +0x16C int iCaptionSize   caption band height (TechWin writes 0x1D @0x487D6C; NetWin 0x1A)
// field: TechWin +0x444  struct Buffer canvas   (+0x4C4 W, +0x4C8 -H; fonts +0x52C/+0x530/+0x534/+0x538)
// field: TechWin +0xA14  int cell_w      n<=8: SW/cols-0x14 else (SW-0x14)/cols, clamp <= SW/3
// field: TechWin +0xA18  int cell_h      cw*3/2, clamp >= SH/2; if ch*rows+0x1D > SH -> SH/rows-0x28 (n<=8) | (SH-0x45)/rows
// field: TechWin +0xA1C  int pad         = 10; top cursor / icon gap
// field: TechWin +0xA20  int faction
// field: TechWin +0xA24  int cols        table[n] @0x487A01..0x487C58 (n=7,8 -> 4)
// field: TechWin +0xA28  int rows        ceil(n/cols)
// field: TechWin +0xA2C  int n_choices
// field: TechWin +0xA38  int hover_idx   seed 0; +0xA3C hover_valid
// field: TechWin +0xA40  int cur_L       cell rect L (content painter scratch)
// field: TechWin +0xA44  int cur_bottom  B-5; unlock lines consume upward
// field: TechWin +0xA48  int cur_W       cell rect R-L
// field: TechWin +0xA4C  int line_h      F0 line metric
// field: TechWin +0xA50  int cur_y       top cursor (T+pad -> name -> category -> icon -> quote)
// field: TechWin +0xA54  int first_flag  0 until the quote is written
// field: TechWin +0xA58  int tech_ids[0x59]
// field: TechWin +0xBBC  struct Font fonts[4] stride 0x28  F0 hud s style0 / F1 s bold / F2 s italic / F3 big bold; s,big = 0xE,0x12 (n<=8; 0xC,0xE @SW800) | 0xA,0xC (n>8); Font_init @0x487999/AE/C2/DA

// ==== Design Workshop screen (DesignWin 0x71F2B0; window h = 600 - [0x7AF59C], 623x387 @(216,168) at 1024x768) ====
extern struct DesignWindow DesignWin_g;                        // addr: 0x0071F2B0  thinker  global DesignWin object; size 0x145B8; vtbl 0x66B148
extern void DesignWin_ctor(/*ecx*/ struct DesignWindow* self); // addr: 0x00434480  observed  fastcall; FlatButton[0x19] array ctor @0x4344CC; vtbls @0x43454C/0x434552/0x43455C
extern void DesignWin_dtor(/*ecx*/ struct DesignWindow* self); // addr: 0x0043ECB0  observed  fastcall
extern int  DesignWin_exec(/*ecx*/ struct DesignWindow* self, int faction, int unit); // addr: 0x0043E9A0  observed  thiscall RET 8; SEH prologue; 6 callers 0x417E05/0x417E47/0x4BAF47/0x583CC0/0x583F00/0x5848A7; calls DesignWin_build @0x43E9DF
extern int  Win_itemdraw_default(struct Win* btn, int a2, int id);         // addr: 0x00404220  observed  `xor eax,eax; ret 0xC`: the vtbl+0x14 item-draw default of 57 Win classes (per FlatButton draw after the face compose)
extern int  DesignWin_build(/*ecx*/ struct DesignWindow* self);            // addr: 0x0043C270  observed  fastcall; ALL rect tables + 3 Font_init + deswin.pcx + GraphicWin_init @0x43C6E4 + Win_move @0x43C718 + 25 BaseButton_init
extern void DesignWin_reset(/*ecx*/ struct DesignWindow* self);            // addr: 0x0043C1A0  observed  fastcall; hide buttons, zero state, Font_close x3
extern void DesignWin_close_external(/*ecx*/ struct DesignWindow* self);   // addr: 0x0043E960  observed  fastcall; TutWin_tour7/tech_achieved close path
extern void DesignWin_repaint(/*ecx*/ struct DesignWindow* self);          // addr: 0x004379A0  observed  fastcall; vtbl+0x30 master content painter
extern void DesignWin_draw_chassis_box(/*ecx*/ struct DesignWindow* self); // addr: 0x00434BC0  observed  fastcall; rect +0xAAC; Caviar zoom 0.05 @0x434D0A
extern void DesignWin_draw_weapon_box(/*ecx*/ struct DesignWindow* self);  // addr: 0x00434F40  observed  fastcall; rect +0xABC; Caviar zoom 0.15/0.06/0.08
extern void DesignWin_draw_armor_box(/*ecx*/ struct DesignWindow* self);   // addr: 0x00435400  observed  fastcall; rect +0xACC; Caviar zoom 0.07 @0x435557
extern void DesignWin_draw_reactor_box(/*ecx*/ struct DesignWindow* self); // addr: 0x00435800  observed  fastcall; rect +0xADC; Caviar zoom 0.2 @0x4359FA
extern void DesignWin_draw_abil1_box(/*ecx*/ struct DesignWindow* self);   // addr: 0x00435B30  observed  fastcall; rect +0xAEC; text only
extern void DesignWin_draw_abil2_box(/*ecx*/ struct DesignWindow* self);   // addr: 0x00435DE0  observed  fastcall; rect +0xAFC; text only
extern void DesignWin_draw_unit_preview(/*ecx*/ struct DesignWindow* self, int a2); // addr: 0x00436090  thinker  fastcall + 1 stack arg; rect +0xA9C; Caviar zoom 0.14 @0x4362BA; timer body
extern void DesignWin_construct_model(/*ecx*/ struct DesignWindow* self);  // addr: 0x0043BF50  observed  fastcall; vehdraw_construct_* into Caviar +0x1279C
extern void DesignWin_draw_title_box(/*ecx*/ struct DesignWindow* self);   // addr: 0x004346A0  observed  fastcall; console center rect +0xA4C -> 0x7AEC64; local Font hud 18 bold @0x43470E
extern void DesignWin_draw_slot_strip(/*ecx*/ struct DesignWindow* self);  // addr: 0x0043D510  observed  fastcall; console rect +0xB0C -> 0x7AEC64; 10 cells cellW=((R-L)+2)/10-2; Buffer_tile @0x43D592
extern void DesignWin_draw_flash(/*ecx*/ struct DesignWindow* self);       // addr: 0x0043DD50  thinker  fastcall; console left box +0xB1C -> 0x7AEC64; chains 0x43D510 @0x43E452
extern void DesignWin_scroll_to_unit(/*ecx*/ struct DesignWindow* self, int unit, int repaint); // addr: 0x0043D490  observed  thiscall RET 8
extern void DesignWin_on_click(/*ecx*/ struct DesignWindow* self, int x, int y);       // addr: 0x00439960  observed  vtbl+0x4C; Spot +0x12764 -> part handlers
extern void DesignWin_on_hover(/*ecx*/ struct DesignWindow* self, int x, int y);       // addr: 0x00439700  observed  vtbl+0x58; bubble text per part box
extern void DesignWin_on_mouse_move(/*ecx*/ struct DesignWindow* self, int x, int y);  // addr: 0x00437BA0  observed  vtbl+0x44
extern int  DesignWin_on_key(/*ecx*/ struct DesignWindow* self, int key, int vk);      // addr: 0x00439A20  observed  vtbl+0x64 RET 8
extern void DesignWin_on_button_clicked(/*ecx*/ struct DesignWindow* self, int id);    // addr: 0x00438460  thinker  vtbl+0xB0 RET 4; ids 0..0x18
extern void DesignWin_pick_chassis(/*ecx*/ struct DesignWindow* self);     // addr: 0x00439F20  observed  thiscall; stack PartPicker 0x4328B0 -> 0x433F70 type 0; inline repaint
extern void DesignWin_pick_weapon(/*ecx*/ struct DesignWindow* self);      // addr: 0x0043A300  observed  thiscall; type 1
extern void DesignWin_pick_armor(/*ecx*/ struct DesignWindow* self);       // addr: 0x0043A760  observed  thiscall; type 2
extern void DesignWin_pick_reactor(/*ecx*/ struct DesignWindow* self);     // addr: 0x0043AA00  observed  thiscall; type 3
extern void DesignWin_pick_ability(/*ecx*/ struct DesignWindow* self, int slot); // addr: 0x0043AC70  observed  thiscall RET 4; Popup_start_2 UNITSPECIAL list
extern int  DesignWin_design_it(/*ecx*/ struct DesignWindow* self);        // addr: 0x00437BF0  thinker  thiscall
extern void DesignWin_select_name(/*ecx*/ struct DesignWindow* self);      // addr: 0x0043BE30  thinker  fastcall; X_pop_ask DESIGNNAME
extern void DesignWin_setup_veh(/*ecx*/ struct DesignWindow* self, int unit, int flag); // addr: 0x0043E490  thinker  thiscall RET 8
extern void DesignWin_abil_validate(/*ecx*/ struct DesignWindow* self);    // addr: 0x00439C00  observed  fastcall
extern void DesignWin_abil_add(/*ecx*/ struct DesignWindow* self, unsigned bit);    // addr: 0x00439D30  observed  thiscall RET 4
extern void DesignWin_abil_remove(/*ecx*/ struct DesignWindow* self, unsigned bit); // addr: 0x00439EB0  observed  thiscall RET 4
extern void DesignWin_show(/*ecx*/ struct DesignWindow* self, int a2);     // addr: 0x0043D0C0  observed  vtbl+0x4; ambience 0xD3 + SubInterface_set_iface_mode
extern void DesignWin_hide(/*ecx*/ struct DesignWindow* self);             // addr: 0x0043D0F0  observed  vtbl+0x8; SubInterface_release_iface_mode + ambience 0xD4
extern void DesignWinIface_on_mode(struct SubInterface* self, int enter);  // addr: 0x0043D120  observed  thiscall RET 4; iface vtbl 0x66B0F4+0; slide_show(win,0) @0x43D1BE / slide_hide on exit
extern void DesignWinIface_on_slot_click(struct SubInterface* self, int x, int y); // addr: 0x0043D220  observed  iface vtbl+0xC; Spot +0x12758 -> setup_veh + full redraw
extern void DesignWinIface_on_slot_hover(struct SubInterface* self, int x, int y); // addr: 0x0043D290  observed  iface vtbl+0x10; bubble
extern void DesignWinIface_on_mouse_move(struct SubInterface* self, int x, int y); // addr: 0x0043D350  observed  iface vtbl+0x20; hovered slot -> draw_flash
extern void DesignWinIface_on_mouse_leave(struct SubInterface* self);      // addr: 0x0043D3C0  observed  iface vtbl+0x24; draw_flash
extern void DesignWin_timer_tick();                                        // addr: 0x0043C170  observed  40ms cb installed @0x43EBA2 (FUN_00616350(cb,0,0x28,5)); draw_unit_preview + GraphicWin_update_2(+0xA9C) + TutWin_draw_arrow
extern struct DesignWindow* g_DesignWin_current;                           // addr: 0x00733970  observed  set by DesignWin_exec, NULL when closed
extern int  g_DesignWin_mode;                                              // addr: 0x0073396C  observed  0 modal / 2 non-modal refresh / 3
extern struct SubInterface* g_current_iface;                               // addr: 0x007AE7F4  observed  written by DesignWin_build @0x43C2C0 and MainWin_build @0x4596D5
extern void PartPicker_ctor(/*ecx*/ struct PartPicker* self);              // addr: 0x004328B0  observed  fastcall; STACK object 0x4668 B; vtbl 0x66B2B8; ScrollBar +0xA14, Caviar +0x2B9C, Buffer +0x406C, Font +0x45F4/+0x461C
extern int  PartPicker_exec(/*ecx*/ struct PartPicker* self, int x, int y, int faction, int type, int cur, int chassis, int weapon, int armor, int abil, int reactor, void* cb); // addr: 0x00433F70  observed  thiscall; GraphicWin_init @0x43424F (w/h = DesignWin canvas, parent DesignWin); 5x4 grid; returns picked idx
extern int  PartPicker_draw_cell(/*ecx*/ struct PartPicker* self, int idx, int sel); // addr: 0x00433D60  observed  thiscall RET 8; cell {col*0x6C+0x1B, row*0x5E+4, +0x69, +0x5B}; box d528/d578 @0x433E2C
extern void PartPicker_dtor(/*ecx*/ struct PartPicker* self);              // addr: 0x0043EE10  observed  fastcall
extern void PartPicker_on_click(/*ecx*/ struct PartPicker* self, int x, int y); // addr: 0x00433820  observed  vtbl+0x44; pointer-move handler; hit col=(x-4)/108 row=(y-4)/94 vs cells drawn at col*108+27 (vanilla off-by-frame); outside-grid path 0x433905 un-hovers via draw_cell @0x433914 WITHOUT the vtbl+0xFC present
extern struct Sprite g_picker_empty_tile;   // addr: 0x006B33F8  observed  Buffer_tile_2 fill of empty PartPicker cells @0x433DDE
// field: PartPicker +0x444 struct Buffer canvas   dest of every cell draw (Caviar_draw dst)
// field: PartPicker +0x2B60 int first_idx   ; +0x2B64 visible (20); +0x2B6C cols (5); +0x2B70 rows (4); +0x2B74 count; +0x2B80 selected; +0x2B84 type
// field: PartPicker +0x45F4 struct Font name_font   size 10 @0x43406F; +0x461C stats font size 12 bold @0x434081
extern void* PartPicker_vtbl;               // addr: 0x0066B2B8  observed  +0x44 on_click 0x433820, +0x30 repaint 0x4339C0, +0x64 on_key 0x433A10
extern void PartPicker_repaint(/*ecx*/ struct PartPicker* self);           // addr: 0x004339C0  observed  vtbl+0x30
extern int  PartPicker_on_key(/*ecx*/ struct PartPicker* self, int key, int vk); // addr: 0x00433A10  observed  vtbl+0x64
extern void PartPicker_on_scroll(/*ecx*/ struct PartPicker* self, int id, int value); // addr: 0x00433F30  observed  thiscall RET 8; vtbl+0xC0 (chevron notify): first_idx [+0x2B60] = cols [+0x2B6C] * value; GraphicWin_redraw vtbl+0xF8; no present
extern void PartPicker_on_scroll_drag(/*ecx*/ struct PartPicker* self, int id, int value); // addr: 0x00433F50  observed  thiscall RET 8; vtbl+0xC4; forwards to vtbl+0xC0
extern int  PartPicker_cell_chassis(/*ecx*/ struct PartPicker* self, int idx, RECT* r, int sel); // addr: 0x004329B0  observed  thiscall; Caviar zoom 0.06
extern int  PartPicker_cell_weapon(/*ecx*/ struct PartPicker* self, int idx, RECT* r, int sel);  // addr: 0x00432CC0  observed  thiscall
extern int  PartPicker_cell_armor(/*ecx*/ struct PartPicker* self, int idx, RECT* r, int sel);   // addr: 0x00433170  observed  thiscall; Caviar zoom 0.1
extern int  PartPicker_cell_reactor(/*ecx*/ struct PartPicker* self, int idx, RECT* r, int sel); // addr: 0x00433520  observed  thiscall; Caviar zoom 0.2
extern void GraphicWin_update_2(struct GraphicWin* self, RECT* rect, int a3); // addr: 0x005D5630  thinker  thiscall; blit rect of window canvas to screen
extern float g_design_preview_angle_step;                                  // addr: 0x0066B420  observed  const 0.05f; preview rotation per tick
// field: DesignWin +0x13C  RECT  screen_rect
// field: DesignWin +0x474  RECT  local_rect        (0,0,623,600-strip)
// field: DesignWin +0xA14  struct SubInterface iface   vtbl 0x66B0F4; +0xA18 mode id 1
// field: DesignWin +0xA4C  RECT  title_box         console center [0x7AF5C0] inset 4
// field: DesignWin +0xA6C  RECT  presets_title     console right [0x7AF5B0] inset 7, h 0x15
// field: DesignWin +0xA7C  RECT  presets_area      console right inset 7, top +0x18
// field: DesignWin +0xA8C  RECT  right_container   console right inset 4
// field: DesignWin +0xA9C  RECT  preview_rect      {0x8C,9,0x1C3,0x140} modal
// field: DesignWin +0xAAC  RECT  part_box[6]       chassis/weapon/armor/reactor/abil1/abil2; stride 0x10
// field: DesignWin +0xB0C  RECT  slot_strip        console: {[0x7AF5A0]+4, box6.T, box6.R, box6.B}
// field: DesignWin +0xB1C  RECT  flash_box         console left: [0x7AF5A0] +3, bottom box6.T-3
// field: DesignWin +0xB2C  RECT  cost_text_rect    output of draw_unit_preview
// field: DesignWin +0xB3C  RECT  name_text_rect    output of draw_unit_preview
// field: DesignWin +0xB4C  RECT  button_rect[9]    index = button id 0..8 (RETIRE,APPLY,PROTO,RETIRE ALL,Done,Rename,OBSOLETE,UPGRADE,Cancel)
// field: DesignWin +0xCBC  RECT  left_arrow_rect   console; rcArrowBtn8 shifted +([0x7AF5A0]-[0x7AF2CC]+8)
// field: DesignWin +0xCCC  RECT  right_arrow_rect  console; = rcArrowRight
// field: DesignWin +0xCDC  int   exec_result
// field: DesignWin +0xCE0  int   hovered_slot_unit (-1 / 0x3F none)
// field: DesignWin +0xCE4  int   slot_scroll_base
// field: DesignWin +0xCE8  int   tick_counter
// field: DesignWin +0xCEC  struct FlatButton buttons[0x19]   stride 0xB4C, index == id; 9..0x16 presets, 0x17/0x18 arrows (parent MainWin)
// field: DesignWin +0x12758 struct Spot slot_spots     cap 0x40
// field: DesignWin +0x12764 struct Spot box_spots      cap 6
// field: DesignWin +0x12770 float preview_angle
// field: DesignWin +0x12774 struct Time timer          0x28 B
// field: DesignWin +0x1279C struct Caviar caviar       0x14D0 B; shared by all part renders
// field: DesignWin +0x13C6C struct Buffer backdrop_pcx deswin.pcx 623x368; w +0x13CEC, h +0x13CF0 (neg)
// field: DesignWin +0x141F4 int faction
// field: DesignWin +0x141F8 int unit_id
// field: DesignWin +0x141FC int chassis
// field: DesignWin +0x14200 int weapon
// field: DesignWin +0x14204 int armor
// field: DesignWin +0x14208 int abil_flags
// field: DesignWin +0x1420C int reactor
// field: DesignWin +0x14214 int cost_factor
// field: DesignWin +0x14218 int abil_slot[2]
// field: DesignWin +0x14220 char name[0x20]
// field: DesignWin +0x14270 char labels[16][0x2D]   DESIGNLABELS
// field: DesignWin +0x14540 struct Font font_body    hud 10 (lead 3) @0x43C2CD
// field: DesignWin +0x14568 struct Font font_title   hud 12 bold (lead 5) @0x43C2EB
// field: DesignWin +0x14590 struct Font font_name    hud 16 bold (lead 4) @0x43C309
// field: Font +0x0 int leading   line pitch = (<0 ? +0xC : +0x10 + leading)

// ==== HQ REPORT screens (ReportWin 0x876478 / ReportIf 0x885F38 mode-5 SubInterface; static map work\_rw_static_map.md) ====
extern void ReportIf_ctor(void);                  // addr: 0x004AD170  observed  thiscall ecx=0x885F38; installs vtbl 0x66D700 (base SubInterface vtbl 0x66A6E4 first)
extern void ReportIf_dtor(void);                  // addr: 0x004ACDA0  observed  thiscall; atexit via CRT stub 0x496920
extern void ReportWin_ctor(void);                 // addr: 0x004AD6B0  observed  thiscall ecx=0x876478; vtbl 0x66D754, canvas vtbl 0x66D74C at +0x444
extern void ReportWin_dtor_body(void);            // addr: 0x004AD3B0  observed  thiscall; scalar dtor wrapper 0x4AD840 (vtbl+0)
extern void ReportWin_win_init(void);             // addr: 0x00496960  observed  fastcall(this=ReportWin); one-time GraphicWin_init; content 650x353 (+0xC8 tall at >=1024), y=ScreenH-h-0xD4
extern void ReportIf_show_page(int kind, int faction, int data); // addr: 0x004A3950  observed  thiscall(this=ReportIf) RET 0xC; central page open/switch; teardown switch on +0x1E1DC (tbl 0x4A3CD4)
extern void ReportIf_activate(int on);            // addr: 0x004A41D0  observed  thiscall(this=ReportIf); ReportIf vtbl+0x00; builds ALL console buttons / full teardown
extern void ReportIf_on_redraw(void);             // addr: 0x004A3FC0  observed  thiscall(this=ReportIf); chrome + per-kind console painter (tbl 0x4A4020); sole E8 caller 0x4CF737
extern void ReportIf_console_chrome(void);        // addr: 0x004A3D20  observed  fastcall(this=ReportIf); 0x78DA50/0x78D5A0/0x78D528 panel frames every repaint
extern void ReportIf_map_spot_click();            // addr: 0x004A5F40  observed  thiscall; ReportIf vtbl+0x0C; kind-7 unit filter via Spot_check
extern void ReportIf_item_selected();             // addr: 0x004A6050  observed  thiscall(this,id); ReportIf vtbl+0x28; kind2/3/4 list select + kind4 sort rebuild
extern void ReportIf_sort_qsort();                // addr: 0x004ACC30  observed  thiscall(this,lo,hi); quicksort of +0x1E258 sort array
extern void ReportIf_blink_step(void);            // addr: 0x004A4060  observed  fastcall(this=ReportIf); base-blink anim: stamps ReportIf+0x20254 dot sprites onto WorldWin canvas 0x8EA3A4 (Sprite_blit_scaled_core x4, jump table 0x4A4194 A A B C D C D C B A A stop)
extern int  WorldWin_tile_to_pixel(int x, int y, int* px, int* py);   // addr: 0x004C44E0  observed  thiscall(this=WorldWin) RET 0x10; stretch branch px=win_w*x/MapSizeX, py=-win_h*y/MapSizeY (traced 80x80: (597*20/80, 297*30/80) = (149,111) @4K); called @0x4974B2 for the blink point
extern void Time_init(void* cb, int arg, int period_ms, int res);     // addr: 0x00616260  observed  thiscall(this=Time) RET 0x10; kills a running timer first
extern int  Time_start(void* cb, int arg, int period_ms, int res);    // addr: 0x00616350  thinker  thiscall(this=Time) RET 0x10; period<50 -> timeSetEvent (callback on another thread)
extern int  Time_start_3(void);                                        // addr: 0x00616650  observed  thiscall(this=Time); period>=50 -> SetTimer(hwnd [0x9B7B28]) else timeSetEvent
extern void Time_stop(void);                                           // addr: 0x00616730  observed  thiscall(this=Time)
extern struct Time g_report_blink_timer;                               // addr: 0x008846EC  observed  = ReportWin+0xE274; bl_daemon 150 ms
extern struct Sprite g_checkbox_sprites[3];                            // addr: 0x007794D8  observed  stride 0x2C: [0] NetWin options unchecked, [1] PrefWin CheckList unchecked (sprite_a 0x779504), [2] checked (sprite_b 0x779530; NetWin_draw_options idx = flag ? 2 : 0)
extern void WorldWin_draw_bases(struct Console* self);          // addr: 0x00469B40  observed  thiscall; minimap base pass over the console's tile window, tiles with [+8]&1 -> MapWin_tile_to_pixel -> MapWin_draw_base_tile(x, y, px, py - [+0x1DDC0]); sole caller WorldWin_on_redraw @0x4C40EF
extern void MapWin_draw_base_tile(struct Console* self, int x, int y, int px, int py, int faction);   // addr: 0x00467190  observed  thiscall RET 0x14; visibility gates (+0x1DD70 & 0x200080) then base_at -> base_draw(canvas +0x444, base, px, py, zoom idx +0x1DD98, (+0x1DD70>>18)&8)
extern int  base_at(int x, int y);                              // addr: 0x004E3A50  thinker  cdecl; base id at tile or -1
extern int  MapWin_tile_to_pixel(struct Console* self, int x, int y, int* px, int* py);   // addr: 0x00462F00  observed  thiscall RET 0x10; console tile -> canvas pixel (PRACX CMAIN_TILETOPT_F); BASE LOCATOR zoom: (4x-8, 2y-6)
extern struct Console PlanWin;                                                  // addr: 0x00834D70  thinker   Go To / battle-plan map panel (a MapWin); canvas Buffer at [[this]+4]+this+0x444
extern void PlanWin_open(struct Console* self, int a2);                         // addr: 0x0048BC60  observed  thiscall RET 4; MapWin_init_2(this,3,0), zoom -14, save Buffer +0x21A70 at the window dims
extern void PlanWin_close(struct Console* self);                                // addr: 0x0048BC50  observed  thiscall; clears +0x21A68
extern void PlanWin_render(struct Console* self);                               // addr: 0x0048B3F0  observed  thiscall; MapWin_draw_map then copies the canvas into +0x21A70
extern void PlanWin_fit_two(struct Console* self, int x1, int y1, int x2, int y2, int a5); // addr: 0x0048B630  observed  thiscall RET 0x14; zoom-fit loop from -14, capped at -10
extern void PlanWin_fit_one(struct Console* self, int x, int y, int a3);        // addr: 0x0048B8E0  observed  thiscall RET 0xC; zoom-fit loop
extern void PlanWin_add_line(struct Console* self, int x1, int y1, int x2, int y2, int colour); // addr: 0x0048AE40  observed  up to 4 lines at +0x2200C, colours +0x21FFC, count +0x21FF8
extern void PlanWin_overlay_draw(void* self);                                   // addr: 0x0048AF30  observed  thiscall this=PlanWin+0x22050; restores +0x21A70, bases, unit, route lines via Buffer_line @0x48B370
extern void PlanWin_blink(struct Console* self);                                // addr: 0x0048BC20  thinker   toggles +0x21A6C, tail-jmps vtbl+0x30
extern int  g_planwin_line_phase;                                               // addr: 0x00939FD4  observed  route-line dash phase, decremented by the line timer 0x50EE80
extern void Console_go_to_select_cb(void* popup, int index);                    // addr: 0x004D6070  observed  Go To list selection: clear lines, fit unit+base, add the unit->base line, overlay redraw
// field: Console +0x21A68 int32 planwin_open   PlanWin open flag
// field: Console +0x21A70 Buffer planwin_save   PlanWin native render copy (window dims)
// field: Console +0x21FF8 int32 planwin_nlines   PlanWin route-line count (<= 4)
// field: Console +0x2200C RECT planwin_lines[4]   PlanWin route lines {x1,y1,x2,y2} in tile coords
// field: Console +0x1DDBC int col_w   x-unit pixel step of the console's canvas (4 x zoom)
// field: Console +0x1DDC8 int zoom    the console's zoom level (col_w = 4z, row_h = 2z)
// field: Console +0x1DDC0 int row_h   tile row pitch of the console's canvas (2 at the BASE LOCATOR zoom; the base pass subtracts it from tile_to_pixel_y)
// field: WorldWindow +0x152C struct Console console   embedded minimap console (0x8EB48C); its canvas = WorldWindow + [[+0x152C]+4] + 0x1970
// field: WorldWindow +0xA1C struct Buffer composed   the console render copied here, then centred 1:1 (+0x239C4/+0x239C8) or StretchBlt'd (Buffer_copy_3) onto +0x444
// field: WorldWindow +0xFA4 struct Buffer render   map render exchanged with the console canvas around WorldWin_draw_bases
// field: WorldWindow +0x239C4 int comp_off_x ; +0x239C8 comp_off_y   1:1 centring offsets of the composed minimap (0 when stretched)
// field: base_draw locator box: console rect (px+3, py, px+9, py+6) half-open, Buffer_box_2 @0x55B126 + Buffer_fill_3 @0x55B155
extern void WorldWin_render_full(struct WorldWindow* self, int a2);   // addr: 0x004C4230  observed  thiscall RET 4; one-shot [0x90D93C]; resizes +0xFA4/+0xA1C buffers, seeds console zoom idx -14 @0x4C42C0, terrain render
// field: WorldWindow +0x152C struct Console console   embedded map console (zoom idx +0x1F2C4, flags +0x1F29C); its canvas = +0x152C+0x23D94+0x444 = 0x90F664
// field: Console +0x0 void* descriptor   0x66EF04 (Console_ctor @0x50F49A); [+4] = 0x23D94 = offset of the Console's GraphicWin member (canvas Buffer at +0x23D94+0x444; MapWin_g canvas 0x939888)
// field: WorldWindow +0x239BC int redraw_flags   8 = recreate buffers (seeds zoom idx -14), 4|1 = terrain pass, 6 = base pass
// field: WorldWindow +0xA14 int buf_w   map-render buffer width = MapAreaX*4*floor((50z+1)/4); +0xA18 buf_h = (MapAreaY/2-2)*same
// field: base_draw colour tables: fill 0x68F9F0, icon-path ring 0x68FA10, icon-path number 0x68FA30 (8 dwords by faction slot); box/icon threshold imm @0x55AF62 (-8; PRACX ZoomedOutShowDetails rewrites it to -14 at startup)
// field: ReportWin +0xE274 struct Time blink_timer   alias 0x8846EC
// field: ReportWin +0x7BF8 RECT btn_row   console DATALINKS / CLOSE row (L,T,R,B) = 0x87E070; ReportWin_show frames it outset 3
// field: ReportInfc +0x20254 struct Sprite dot_sprites[4]   0x2C ea; dot0..3.pcx 12x12 key 9 (init_report_screen loop 0x4A34EB)
// field: WorldWindow +0x444 struct Buffer canvas   alias 0x8EA3A4; blink stamp dest
// field: WorldWindow +0x239C4 int center_off_x   1:1-centred branch (0 on the stretch branch)
// field: WorldWindow +0x239C8 int center_off_y
extern void bl_daemon();                          // addr: 0x004A4050  observed  cdecl timer cb (arg=ReportIf), 150ms base blink
extern void report_close(void);                   // addr: 0x004A3930  observed  Win_release_modal + SubInterface_release_iface_mode
extern void ReportWin_on_paint(void);             // addr: 0x00496D00  observed  fastcall(this=ReportWin); vtbl+0x30; tech_reset then kind dispatch to page painters
extern void ReportWin_show_vslot(void);           // addr: 0x004A5F00  observed  vtbl+0x04; pushes iface mode 5 (ecx=ReportIf)
extern void ReportWin_hide_vslot(void);           // addr: 0x004A5F20  observed  vtbl+0x08; pops iface mode 5
extern void ReportWin_on_lclick();                // addr: 0x00496E10  observed  thiscall(this,x,y); vtbl+0x4C; Spot_check row/garrison/psych/goal clicks; calls painters INLINE
extern void ReportWin_on_rclick();                // addr: 0x00497F00  observed  thiscall(this,x,y); vtbl+0x58; kind6 scenario sat_edit @0x497FA8
extern void ReportWin_on_dblclick();              // addr: 0x00497A60  observed  vtbl+0x70; kind4 base -> BaseWin zoom
extern void ReportWin_on_key();                   // addr: 0x00498280  observed  thiscall(this,?,key); vtbl+0x64; F2..F8 = kinds 2..8, 0x25/0x27 cycle, PgUp/Dn scroll
extern void ReportWin_on_group_changed();         // addr: 0x004989F0  observed  thiscall; vtbl+0xB8; type4 -> [0x8A4178]=id; type6 -> console repaint (kind-switch copy #4)
extern void ReportWin_on_scroll_a();              // addr: 0x00498180  observed  vtbl+0xC0; writes +0xC0FC; kind5 rebuilds
extern void ReportWin_on_scroll_b();              // addr: 0x00498200  observed  vtbl+0xC4; same body as 0x498180
extern void ReportWin_on_list_select();           // addr: 0x0049D490  observed  thiscall(this,id); vtbl+0xD4; energy page +0x59AC/+0x59B0 -> rebuild
extern void ReportWin_set_scroll();               // addr: 0x00498110  guess  thiscall(this,pos,min,max,page); no static callers found
extern void ReportWin_draw_energy(void);          // addr: 0x0049BCD0  observed  fastcall(this=ReportWin); kind 3 canvas painter
extern void ReportWin_draw_ops(void);             // addr: 0x0049D540  observed  fastcall; kind 4 canvas painter (thinker ReportWin::draw_ops)
extern void ReportWin_draw_projects(void);        // addr: 0x0049EB10  observed  fastcall; kind 5 canvas painter
extern void ReportWin_draw_sat(void);             // addr: 0x0049F350  observed  fastcall; kind 6 canvas painter (attack/survey on +0x9F04==0xD3C)
extern void ReportWin_draw_units(void);           // addr: 0x004A08E0  observed  fastcall; kind 7 canvas painter
extern void ReportWin_draw_score(void);           // addr: 0x004A1140  observed  fastcall; kind 8 canvas painter
extern void ReportWin_draw_intel(void);           // addr: 0x004A2210  observed  fastcall; kind 0 canvas painter
extern void ReportIf_console_labs(void);          // addr: 0x004A7000  observed  fastcall(this=ReportIf); kind 2 console panels
extern int   labs_write(int win, int item);          // addr: 0x004A8440  observed  cdecl; ListBox item colour cb ([ReportIf+0xA304]); set_text_color3(mandate_color(tech_category(item)))
extern void  ReportIf_hide_labs_widgets(void);       // addr: 0x004A8470  observed  thiscall(this=ReportIf); ListBox_close(+0xA2D0) + hide toggles 0x92/0x93
extern void  scroll_normal(void);                    // addr: 0x00588340  observed  cdecl; scrollbar art globals 0x9B8DE8..0x9B8E1C <- 0x791D88.. (0x2C stride), trough 0x79A5E8, g_scrollbar_w=0x14
extern void  scroll_small(void);                     // addr: 0x005883D0  observed  cdecl; same globals <- 0x78DE30+i*0x2C (12x 10x10 arrows), trough 0x7796B0 (10x10), g_scrollbar_w=0xC
extern void  load_interface_boxsets(void);           // addr: 0x00453B43  observed  loop in the UI-atlas builder: fills BoxSpriteParams 0x78D528+k*0x28 (k<51) from interface.pcx, 3 sets/row at x=0x21+col*0x27, y=0xE5+row*0x27
extern struct BoxSpriteParams DAT_0078dac8;          // addr: 0x0078DAC8  observed  set #36; EXPLORE bar FULL (filled 24x24 P2 dither)
extern struct BoxSpriteParams DAT_0078db18;          // addr: 0x0078DB18  observed  set #38; EXPLORE bar EMPTY / F2 header spacer state 0
extern struct BoxSpriteParams DAT_0078db40;          // addr: 0x0078DB40  observed  set #39; DISCOVER bar FULL
extern struct BoxSpriteParams DAT_0078db90;          // addr: 0x0078DB90  observed  set #41; DISCOVER bar EMPTY / F2 header spacer state 1
extern struct BoxSpriteParams DAT_0078dbb8;          // addr: 0x0078DBB8  observed  set #42; BUILD bar FULL
extern struct BoxSpriteParams DAT_0078dc08;          // addr: 0x0078DC08  observed  set #44; BUILD bar EMPTY / F2 header spacer state 2
extern struct Buffer g_boxset_fill[51];              // addr: 0x0075C218  observed  0x588 stride; 24x24 fill Buffers ([params+0x20]; NULL when atlas px(0,0)==9)
extern struct Sprite g_scroll_small_sprites[12];     // addr: 0x0078DE30  observed  0x2C stride; 10x10 small scrollbar arrows from interface.pcx (0xC0+0xB*s, 1+0xB*grp)
extern struct Sprite g_scroll_small_trough;          // addr: 0x007796B0  observed  10x10 small scrollbar trough tile at (0xE1,1)
// field: ReportInfc +0x4F94 Sprite tab_sprites[21]   0x2C ea (kind*3+state); +0x4FAC/+0x4FB0 == sprite[0].canvas_w/h (0x1E/0x24)
// field: ReportInfc +0xA2D0 Dialog labs_list          ListBox; [+0xA2E0] sel colour 0xF2; [+0xA304] item colour cb labs_write; row pitch [Dlg+0x48] = +0x1C+3
// field: ReportInfc +0xB978 ButtonGroup labs_toggles  members 0x92 (+0xBA0C) / 0x93 (+0xC558)
extern void ReportIf_console_energy(void);        // addr: 0x004A84A0  observed  fastcall; kind 3 console panels
extern void ReportIf_console_ops(void);           // addr: 0x004A9050  observed  fastcall; kind 4 console panels
extern void ReportIf_console_projects(void);      // addr: 0x004AA0B0  observed  fastcall; kind 5 console panels
extern void ReportIf_console_sat(void);           // addr: 0x004AA970  observed  fastcall; kind 6 console panels (inline ButtonGroup build)
extern void ReportIf_console_units(void);         // addr: 0x004AB600  observed  fastcall; kind 7 console panels
extern void ReportIf_console_score(void);         // addr: 0x004ABE70  observed  fastcall; kind 8 console panels
extern void ReportIf_console_intel(void);         // addr: 0x004AC140  observed  fastcall; kind 0 console panels
extern void report_labs(void);                    // addr: 0x004AC9A0  thinker  kind=2 entry (F2)
extern void report_energy(void);                  // addr: 0x004AC9F0  thinker  kind=3 entry
extern void report_ops(void);                     // addr: 0x004ACA40  thinker  kind=4 entry (base status)
extern void report_projects(void);                // addr: 0x004ACA90  thinker  kind=5 entry
extern void report_sat(void);                     // addr: 0x004ACAE0  thinker  kind=6 entry
extern void report_security(void);                // addr: 0x004ACB30  thinker  kind=7 entry (units/military)
extern void report_score(void);                   // addr: 0x004ACB80  thinker  kind=8 entry
extern void report_intel(int faction);            // addr: 0x004ACBD0  thinker  kind=0 entry; arg -> [0x8A4164]
extern void sat_attack();                         // addr: 0x004A0260  thinker  popup flow; sole caller 0x49897F (tech_button sat path)
extern void sat_edit(int f, int a, int b);        // addr: 0x004A0810  thinker  scenario-editor rclick on sat page
extern void sat_anim_daemon();                    // addr: 0x0049FFC0  thinker  cdecl timer cb, 4000ms orbit anim (pointer-registered)
extern void sat_expl_daemon();                    // addr: 0x004A0250  thinker  cdecl timer cb, 50ms attack explosion
extern void sat_expl_start();                     // addr: 0x0049FFD0  observed  thiscall; Time_init(sat_expl_daemon,&ReportWin_g,0x32,5)
extern void sat_expl_step(void);                  // addr: 0x004A0100  observed  fastcall(this=ReportWin); explosion frame: Buffer_draw 1:1 patch restore + Sprite_draw_table frame @0x4A020C
extern void ReportWin_sat_frame(void);            // addr: 0x0049FE40  observed  fastcall(this=ReportWin); orbit anim frame: planet flic Buffer_draw @0x49FF38
extern int  Buffer_draw(/*ecx*/ struct Buffer* src, struct Buffer* dst, int key, int x, int y); // addr: 0x005D8370  observed  thiscall RET 0x10; keyed blit under SCALE_NUM_G/DEN_G (memory path: builds g_buffer_draw_sprite, calls Sprite_blit_scaled_core; [+0x58] surface path unscaled)
extern struct Sprite g_buffer_draw_sprite;        // addr: 0x009B3A50  observed  Sprite Buffer_draw builds from its src Buffer: data [+0x54] -> +4, key -> +8, pitch [+0x4A8] -> +0xC, W [+0x80] -> +0x10/+0x18, H -[+0x84] -> +0x14/+0x1C, offsets +0x20/+0x24 = 0
extern void SubInterface_set_iface_mode(void);    // addr: 0x0045D310  observed  fastcall(this=SubInterface); pushes mode this+4 onto 0x7AE778 stack
extern void hall_of_fame(int show);               // addr: 0x0044AE50  thinker  cdecl; loads/saves hallfame.jhh; Win_set_modal on FameWin
extern int  pop_wait();                           // addr: 0x005398E0  observed  modal wait callback (2nd arg of Win_set_modal in every report_* wrapper + DatalinkWin)
extern struct GraphicWin FameWin_g;               // addr: 0x0074DAF8  thinker  Hall of Fame window (typedef GraphicWin FameWindow)
extern void* ReportWin_vtbl;                      // addr: 0x0066D754  observed  +4 show,+8 hide,+0x30 paint,+0x4C lclick,+0x58 rclick,+0x64 key,+0xB0 btn,+0xB8 group,+0xC0/C4 scroll,+0xD4 listsel
extern void* SubInterface_base_vtbl;              // addr: 0x0066A6E4  observed  shared base vtbl of every SubInterface
extern struct SubInterface* g_iface_ptr_table[];  // addr: 0x007AE7F0  observed  SubInterface* per mode; [5]=&ReportIf (alias 0x7AE804), [8]=&DatalinkWin iface
extern int  reportwin_opponent_faction;           // addr: 0x008A4164  observed  set by report_intel(faction); = ReportIf+0x1E22C data arg
extern int  g_report_wide_flag;                   // addr: 0x008A4168  observed  = ReportIf+0x1E230; 0 iff ScreenWidth==800 (Holobook keys on it too)
extern int  g_reportwin_sort_mode;                // addr: 0x0087BE80  observed  = ReportWin+0x5A08; kind-4 sort column 0..8
extern int  g_reportwin_sel_item;                 // addr: 0x0087BE24  observed  = ReportWin+0x59AC
extern int  g_reportwin_sel_isbase;               // addr: 0x0087BE28  observed  = ReportWin+0x59B0
extern int  g_report_scroll_active;               // addr: 0x00882570  observed  = ReportWin+0xC0F8
extern int  g_report_modegrp_sel;                 // addr: 0x008A4178  observed  = ReportIf+0x1E240; mode-tab sel id (0x8B3.. / 0xD3C..)
extern int  g_report_unit_filter;                 // addr: 0x008A417C  observed  = ReportIf+0x1E244; kind-7 class filter
extern int  g_report_sort_spots;                  // addr: 0x008A4190  observed  = ReportIf+0x1E258; 0x200 x 16B {idx,key,idx,key}
extern int  g_report_activate_guard;              // addr: 0x008A6240  observed  ReportIf_activate reentry flag
// field: ReportWin +0x474  RECT local_rect     (0,0,w,h) window-local; screen rect at +0x13C (GraphicWin base)
// field: ReportWin +0x5974 RECT content_clip   {0x1A,3,w+0x14,textB}; aliases 0x87BDEC..F8
// field: ReportWin +0x5984 RECT frame_rect     {0x17,0,0x17+w,h}; d690 window frame
// field: ReportWin +0x5990 int  frame_bottom   frame_rect.bottom = window height h
// field: ReportWin +0xA14 RECT page_rect      x,y,w,h: window rect at init, content_clip as x,y,w,h after each page paint
// field: ReportWin +0x599C int  page_scratch   per-kind cell dims follow: +0x59A0 btn_w / +0x59A4 btn_h / +0x59A8 card_w (kind4 0x28/0x28, kind5 colW/0x36, kind6 0x240/0xD2)
// field: ReportWin +0x59B4 uint base_sel_mask[16]   alias 0x87BE2C
// field: ReportWin +0x59F4 uint unit_sel_mask[4]    alias 0x87BE6C; +0x5A04 single_sel alias 0x87BE7C
// field: ReportWin +0x5A0C struct ListBox energy_list   font [0x8A40BC]
// field: ReportWin +0x6560 struct FlatButton btn_id9 ; +0x70AC btn_id1   console strip row y=textB+7 h 0x14
// field: ReportWin +0x7BF8 struct ButtonGroup grp1   row rect aliases 0x87E070..7C; sel id +0x7C8C
// field: ReportWin +0x7C9C struct FlatButton mode_btn_8B3 ; +0x87E8 8B4 ; +0x9334 8B5   kind-4 mode tabs
// field: ReportWin +0x9E80 struct ButtonGroup grp2   sel id +0x9F04 (sat 0xD3C attack / 0xD3D survey)
// field: ReportWin +0x9F14 struct FlatButton sat_btn_D3C ; +0xAA60 D3D ; +0xB5AC D3E (=0x881A24, ATTACK!)
// field: ReportWin +0xC0F8 struct ScrollBar scroll   pos +0xC0FC min +0xC100 max +0xC104 page +0xC108; inner win +0xC10C (alias 0x882584); thumb +0xCB4C
// field: ReportWin +0xE258 RECT row_rect      alias 0x8846D0; ScrollBar_attach_rect target
// field: ReportWin +0xE268 int  row_line_h    line height of font12 [0x8A40BC] -- row-pitch source of every page
// field: ReportWin +0xE26C int  scroll_need   alias 0x8846E4; +0xE270 scroll_reinit alias 0x8846E8
// field: ReportWin +0xE2A0 RECT sat_orbit_rects   ..+0xE2BC; +0xE8A8 Flic sat2 (satellite.flc); +0xF3D0/+0xF3D4 flic w/h; +0xF938..+0xFA78 orbit float tables
// field: ReportInfc +0x04 int iface_mode_id   = 5; +0x08 cur_kind
// field: ReportInfc +0x0C int cur_x ; +0x10 cur_y ; +0x14 cur_w ; +0x18 cur_h   console panel text cursor
// field: ReportInfc +0x1C int font12_line_h
// field: ReportInfc +0x20 RECT panel_left    console left panel (MainWin coords); +0x30 RECT panel_right
// field: ReportInfc +0x50 int  right_panel_x  console right column x; cur_x >= it -> the right panel's list
// field: ReportInfc +0x1E180 struct Font* fonts[15]   report font table (find_font at init; idx 11..14 = f26/f18/f22/f32)
// field: ReportInfc +0x1E1C8 RECT btn_rect_scratch   L/T/R/B staging for the console BaseButton_init calls
// field: ReportInfc +0x20 RECT panelL ; +0x30 RECT panelR ; +0x40 RECT tabstrip ; +0x50 RECT center   copies of HUD regions 0x7AF5A0/B0/D0/C0
// field: ReportInfc +0x60 int faction_tab_x[7] ; +0x7C int faction_tab_y
// field: ReportInfc +0x80 struct FlatButton faction_tab[7]  stride 0xB4C ids 10000+f
// field: ReportInfc +0x4FAC int tabspr_w ; +0x4FB0 int tabspr_h   0x1E x 0x24 from report.pcx 7x3 grid
// field: ReportInfc +0x4FC0 struct Sprite tab_sprites[21]  0x2C ea (7 kinds x 3 states)
// field: ReportInfc +0x5330 struct Sprite* flag_spr[7][3]  -> 0x78F554 console flag sprites
// field: ReportInfc +0x5384 struct FlatButton kind_tab[7]  stride 0xB4C ids 2..8; xs +0xA298[7]; y +0xA2CC
// field: ReportInfc +0xBA0C struct BaseButton tech_toggle_92 ; +0xC558 93 ; +0xD138 D0A ; +0xDC84 D0B
// field: ReportInfc +0xE7D0 struct BaseButton gov_btn[7]  ids 0xCEF..0xCF5 stride 0xB4C
// field: ReportInfc +0x1BF9C struct BaseButton unit_btn_CF6 ; +0x1CAE8 CF7 ; +0x1D634 CF8
// field: ReportInfc +0x1E180 struct Font* fonts[15]  f10,f12,f12b2,f12b1,f14,f14b2,f14b1,f16,f16b2,f16b1,f11,f26,f18b2,f22,f32; aliases 0x8A40BC=+0x1E184 etc.
// field: ReportInfc +0x1E1BC struct Spot spots   console click targets
// field: ReportInfc +0x1E1DC int kind_history[19]   current at +0x1E1DC
// field: ReportInfc +0x1E228 int faction   alias 0x8A4160; +0x1E22C data alias 0x8A4164; +0x1E230 wide alias 0x8A4168
// field: ReportInfc +0x1E234 int in_activate ; +0x1E238 activating ; +0x1E23C needs_refresh
// field: ReportInfc +0x1E248 int blink_state ; +0x1E24C blink_x ; +0x1E250 blink_y   aliases 0x8A4180/84/88
// field: FameWin +0xA44 int line_h   of font [0x8A40C8]; +0xA48 wide flag copy; +0xA918 sel cache
// field: FameWin +0x5A04 struct BaseButton cat_btn[6]  stride 0xB4C ids 0x8AE.. (0x4F sq, hoficons sprites)
// field: FameWin +0xA5C  struct BaseButton faction_btn[7]  stride 0xB4C ids 1..7 (0x46 sq, flag sprites 0x78F5D8+f*0x65C)
// field: FameWin +0x9DCC struct BaseButton close_btn  id 0x7B8; box-sprite triple 0x78DC80/58/30 at +0xA894..
// field: FameWin +0xB42C int rect_table[24]   6 RECTs: 3 stat boxes, category-btn row, faction-btn row, center box (content-origin-relative)
extern void FameWin_draw(/*ecx*/ struct GraphicWin* self);   // addr: 0x00448D90  observed  fastcall; vtbl 0x66C268 painter: frame.pcx/hof.pcx copy_4, map pcx, faction picture blit-core, band/title/panel titles/score rows
// field: FameWin +0xA14 int scratch_x   content origin x at build (0x77), then icon-loop x / panel text x in the painter
// field: FameWin +0xA18 int scratch_y   content origin y at build (0x50), then icon-loop y / panel text y
// field: FameWin +0xA1C int canvas_w    800 at build, then the button cell pitch, then the analysis text width
// field: FameWin +0xA20 int canvas_h    600 at build, then the analysis text height
// field: FameWin +0xA24 RECT content_rect   (0x77, 0x50, 0x77+800, 0x50+600) in the wide layout; painter clip
// field: FameWin +0xA34 RECT scratch_rect   CLOSE rect at build; TOP 5 row rect in the painter
// field: FameWin +0xA91C struct Buffer frame_pcx   1024x768 frame.pcx, copy_4 1:1 at (0,0) @0x448DFC
// field: FameWin +0xAEA4 struct Buffer hof_pcx     800x600 hof.pcx, copy_4 1:1 at the content origin @0x448E32
// field: FlatButton +0xAB8 int forced_state   painter sets 2 (has data) / -1 on the category buttons before redraw
// field: FlatButton +0xAD4 struct Sprite* state_sprite[3]   +0xAD4/+0xAD8/+0xADC; FlatButton_content_draw blits [state] centred at 1/1 @0x607F43

// ==== Planetary Monument screen (MonumentWin 0x7F9F58; static map work\_mon_static_map.md) ====
extern struct GraphicWin MonumentWin_g;        // addr: 0x007F9F58  observed  0x36DC B; vtbl 0x66C880, canvas sub-vtbl 0x66C878
extern void monument(int show_plaque);         // addr: 0x00476A50  thinker   cdecl; 0 = far/pyramid view (F9, menu 0x110), 1 = near/plaque view (milestone triggers)
extern void clear_monuments(void);             // addr: 0x00476B30  thinker   cdecl; zeroes 21 records + selected := -1 for every faction
extern void MonumentWin_ctor(/*ecx*/ struct GraphicWin* self); // addr: 0x00477C80  observed  fastcall; static-init thunk 0x472200
extern void MonumentWin_dtor(/*ecx*/ struct GraphicWin* self); // addr: 0x00477B10  observed  fastcall; atexit thunk 0x472220
extern void MonumentWin_draw(/*ecx*/ struct GraphicWin* self); // addr: 0x004736E0  observed  vtbl+0x30; far/near fork @0x47378F; 21-case jump table 0x476704
extern void MonumentWin_on_mouse_move(/*ecx*/ struct GraphicWin* self, int x, int y); // addr: 0x00476850  observed  vtbl+0x44 RET 8; far view only; Spot hover re-blits the picture window
extern void MonumentWin_on_lclick(/*ecx*/ struct GraphicWin* self, int x, int y); // addr: 0x00476780  observed  vtbl+0x4C RET 8; near view -> back to far; far view -> Spot_check selects and opens the plaque
extern int  MonumentWin_on_key(/*ecx*/ struct GraphicWin* self, int key, int vk); // addr: 0x00476A00  observed  vtbl+0x64 RET 8; any key = back / close
extern void MonumentWin_on_button_clicked(/*ecx*/ struct GraphicWin* self, int id); // addr: 0x004769B0  observed  vtbl+0xB0 RET 4; id 0x3E7 only
extern int  g_monument_count;                  // addr: 0x007FD634  observed  achieved-milestone count; drives FLC frame count and monzoom1/2 choice
extern char g_monument_wintitle_800[];         // addr: 0x007FD63C  observed  empty static title passed to GraphicWin_init (800x600 branch)
extern char g_monument_wintitle_1024[];        // addr: 0x007FD640  observed  empty static title passed to GraphicWin_init (1024x768 branch)
extern struct Monument Monuments[];            // addr: 0x0094CA08  thinker   stride 0x4F4 per faction; 21 records of 0x38 then selected +0x498, name +0x4AC
extern void mon_colony_founded(int faction, char* base_name); // addr: 0x00476B70  thinker  kind 0
extern void mon_tech_discovered();             // addr: 0x00476C90  thinker   kind 1
extern void mon_secrets_of_tech();             // addr: 0x00476DA0  thinker   kind 2
extern void mon_prototype_built();             // addr: 0x00476EE0  thinker   kind 3
extern void mon_facility_built();              // addr: 0x00476FE0  thinker   kind 4
extern void mon_secret_project();              // addr: 0x00477100  thinker   kind 5
extern void mon_enemy_destroyed();             // addr: 0x00477210  thinker   kind 6
extern void mon_conquer_base();                // addr: 0x00477320  thinker   kind 7
extern void mon_naval_unit_built();            // addr: 0x00477440  thinker   kind 8
extern void mon_air_unit_built();              // addr: 0x00477540  thinker   kind 9
extern void mon_native_life_bred();            // addr: 0x00477640  thinker   kind 0xA
extern void mon_first_in_space();              // addr: 0x00477740  thinker   kind 0xB
extern void mon_built_preserve();              // addr: 0x00477840  thinker   kind 0xC
extern void mon_winning_unify();               // addr: 0x00477940  thinker   kind 0xD
extern void mon_winning_trans();               // addr: 0x004779D0  thinker   kind 0xE
extern void mon_killed_faction();              // addr: 0x00477A60  thinker   kinds 0xF..0x14 (first free kill slot)
// field: MonumentWin +0xA14 int scratch_x ; +0xA18 int scratch_y   content origin at build start, then the sprite-extract cursor
// field: MonumentWin +0xA1C int canvas_w = 800 ; +0xA20 int canvas_h = 600   constant in both modes
// field: MonumentWin +0xA24 RECT content   (0,0,800,600) at 800x600, (112,84,912,684) at 1024x768
// field: MonumentWin +0xA34 RECT scratch   button rect and per-blit rect copies
// field: MonumentWin +0xA44 int line_h   of font [0x8A40BC]; +0xA48 wide flag copy of 0x8A4168
// field: MonumentWin +0xA4C int view_state   0 = far/pyramid, 1 = near/plaque; alias 0x7FA9A4
// field: MonumentWin +0xA50 int faction ; +0xA54 int selected_spot   spot ids 0..14 kinds, 15..20 kills, 0x45 picture window
// field: MonumentWin +0xA58 struct FlatButton btn_close   id 0x3E7, shown in the far view; box-sprite triple 0x78DC80/58/30
// field: MonumentWin +0x15A4 struct FlatButton btn_back   id 0x3E7, shown in the near view
// field: MonumentWin +0x20F0 struct Spot spots   Spot_init capacity 0x40
// field: MonumentWin +0x20FC struct Buffer flic_canvas   1024x768; monument.flc frames composited here
// field: MonumentWin +0x2684 struct Buffer zoom_canvas   monzoom1.pcx (count<5) or monzoom2.pcx
// field: MonumentWin +0x2C0C struct Sprite icons[15]   stride 0x2C; 44x42 monicons.pcx cells
// field: MonumentWin +0x2EA0 struct Sprite big_pics[15]   stride 0x2C; 160x97 monicons.pcx cells
// field: MonumentWin +0x3134 RECT rc_pic_far   (319,202,479,299) content-relative; the FLC keyed picture window
// field: MonumentWin +0x3144 RECT rc_text   (144,47,659,91) content-relative; the plaque text clip/write rect
// field: MonumentWin +0x3154 RECT rc_pic_near   (101,118,701,478) content-relative; the monzoom keyed picture window
// field: MonumentWin +0x3164 RECT rc_icons[14]   stride 0x10; 44x42 slots (the loop reads 15 -- see _mon_static_map.md H1)
// field: MonumentWin +0x3244 struct Sprite banner[6]   stride 0x2C; 3 left/right pairs from monicons.pcx
// field: MonumentWin +0x334C RECT rc_banner[6]   stride 0x10; left/right pairs for 1-2, 3-4, 5-6 kill glyphs
// field: MonumentWin +0x33AC struct Sprite fac_glyphs[7]   stride 0x2C; 58x50 from <faction>3.pcx (10,178)
// field: MonumentWin +0x34E0 struct Sprite fac_pics[7]   stride 0x2C; 160x97 from <faction>3.pcx (164,109)
// field: MonumentWin +0x3614 struct Sprite own_fac_pic   160x97 from the current faction's 3.pcx (164,11)
// field: MonumentWin +0x3640 struct Sprite emblem   71x64 (10,113) or 142x101 (10,11) when count==14
// field: MonumentWin +0x366C RECT rc_glyphs[6]   stride 0x10; T=511 B=561 content-relative
// field: MonumentWin +0x36CC RECT rc_emblem   (364,111,435,175), or (328,6,470,107) when count==14
// field: Monument +0x000 record[21]   stride 0x38; r 0..14 = milestone kinds, r 15..20 = killed-faction slots
// field: MonumentRecord +0x00 int year ; +0x08 int payload ; +0x0C int other_faction ; +0x10 int achieved ; +0x14 int variant
// field: Monument +0x498 int selected   kind currently shown; -1 = none
// field: Monument +0x4AC char name[0x18]   first base name (mon_colony_founded)

// ==== AI unit visibility + net upkeep (AI perception filter) ====
extern int  enemy_move(int veh_id);                                  // addr: 0x0056B5B0  thinker  cdecl; AI per-unit decide
extern int  enemy_veh(int veh_id);                                   // addr: 0x00579240  thinker  cdecl; enemy_move then action
extern void enemy_turn(int faction_id);                              // addr: 0x00579510  thinker  cdecl; runs on every net peer
extern void spot_all(int veh_id, int flag);                          // addr: 0x005B6260  thinker  cdecl; recompute visibility on move
extern void spot_stack(int veh_id, int faction_id);                  // addr: 0x005B58E0  thinker  cdecl; set visibility bit for stack
extern void unspot_stack(int veh_id);                                // addr: 0x005B5A70  thinker  cdecl
extern void spot_loc(int x, int y, int faction_id);                  // addr: 0x005B5AD0  thinker  cdecl
extern int  stack_check(int veh_id, int type, int a3, int a4, int a5); // addr: 0x005B9580  thinker  cdecl
extern int  net_upkeep_phase(int phase);                             // addr: 0x00528EA0  thinker  cdecl; barrier, server sends 0x4303
extern void net_upkeep(void);                                        // addr: 0x005290A0  thinker  cdecl
extern void message_data(int msg, int dest, int p1, int p2, int p3, int p4); // addr: 0x00592EE0  thinker  cdecl; 0x20-byte msg
extern int  NetDaemon_process_message();                              // addr: 0x00534400  thinker  thiscall; msg ptr = arg1
extern int  g_net_is_server;                                         // addr: 0x0093E8C0  observed  nonzero on the host
extern int  g_net_upkeep_phase;                                      // addr: 0x0093A93C  observed  current upkeep phase index
extern int  MultiplayerActive;                                       // addr: 0x0093F660  thinker  net game (DirectPlay/TCP)
// field: VEH +0x27 uint8_t visibility   per-faction bitmask
// field: NetMsg +0x00 uint16_t id ; +0x04 int sender ; +0x08 uint32_t time ; +0x10 int p1 ; +0x14 int p2 ; +0x18 int p3 ; +0x1C int p4
extern int  veh_at(int x, int y);                                    // addr: 0x005BFE90  thinker  cdecl; any unit on the tile or -1
extern int  veh_who(int x, int y);                                   // addr: 0x00500250  thinker  cdecl; owner of the tile's units or -1
extern int  anything_at(int x, int y);                               // addr: 0x005798E0  thinker  cdecl; owner of base/units or -1
extern int  order_veh(int veh_id, int dir, int a3);                  // addr: 0x005947C0  thinker  cdecl; one step, dir 0..7
extern int  action(int veh_id);                                      // addr: 0x004CF740  thinker  cdecl; 1 if an order ran
extern int  Path_find(struct Path* self, int x1, int y1, int x2, int y2, int unit_id, int faction, int flags, int last_dir); // addr: 0x0059A530  thinker  thiscall RET 0x20; first step direction 0..7 toward (x2,y2), -1 = no path
extern int  Path_move(struct Path* self, int veh_id, int faction);  // addr: 0x0059BC10  thinker  thiscall RET 8; go-to step toward waypoint slot 0: Path_find, else (state 0x1000200 both set: order cleared) the greedy neighbour by hex_cost + 32*dist, -1 + veh_skip when none enterable
extern int  action(int veh_id);                                      // addr: 0x004CF740  thinker  cdecl; order dispatcher: 4..0x17 terraform, 0x1B/0x1C road_to, 0x18/0x19/0x58 go_to; clears an order with bit 0x40 after
extern int  NetDaemon_action(struct NetDaemon* self, int veh_id, int release); // addr: 0x00532570  thinker  thiscall RET 8; single player = action(veh)
extern void Console_human_turn(struct Console* self);               // addr: 0x00514050  thinker  fastcall; the human turn: ControlTurnMove==0 -> Console_set_move(0); else MoveMode==0 -> view-mode refresh block, else Console_set_move(1) @0x5140E1; then Console_veh_turn per unit
extern void Console_ready(struct Console* self);                    // addr: 0x00510F50  thinker  fastcall; picks the next ready unit (Console_ready_search) into CurVeh; returns early when MoveMode == 0
extern void load_daemon(void);                                      // addr: 0x005A9760  thinker  cdecl; load_game / load_undo / show_replay tail; the block @0x5A9A64 (MoveMode := 0, GameState |= 0x10C0) runs only for a save whose name contains "multi"; the join @0x5A9AA2 sets ControlTurnMove := CurrentPlayerFaction (uimod hudsync detours it to also set MoveMode := 1 in single player)
extern int  ControlTurnMove;                                        // addr: 0x009B2070  thinker   nonzero = a human turn is in progress; load_daemon sets it to CurrentPlayerFaction
extern int  Console_veh_turn(struct Console* self);                 // addr: 0x00513B90  thinker  fastcall; the current unit's order loop: NetDaemon_action per step, 100 failed steps cancel a go-to @0x513E27 (uimod hudmovesfix repaints the HUD there) / veh_skip other orders; redraw block @0x513D16..0x513D2B (draw_cursor, StatusWin_redraw, caption)
extern void veh_skip(int veh_id);                                    // addr: 0x005C1D20  thinker  cdecl; moves_spent (+0x28) = speed: the unit is done for the turn
extern void action_go_to(int veh_id);                                // addr: 0x004CB310  thinker  cdecl; per-turn go-to executor: Path_move -> order_veh(dir, 3); on reaching slot 0 with state 0x2000200 rotates the waypoint slots down (count--), clears the path state at 0
extern int  territory(int owner, int intruder, int flags, int* base, int* cnt); // addr: 0x0055EB80  thinker  cdecl; intruder unit count
extern int  do_withdrawal(int owner, int intruder);                  // addr: 0x00548F80  thinker  cdecl; returns units moved
extern int  demand_withdrawal(int faction, int target);              // addr: 0x00549270  thinker  cdecl
extern int  communicate(int faction, int speaker, int a3);           // addr: 0x0054FFD0  thinker  cdecl; AI-initiated talk
extern void demands_withdrawal(int faction, int target);             // addr: 0x0053E4C0  thinker  cdecl; commlink menu entry
extern int  X_pops_11(const char* label, int flags, void* sprite, void* fn); // addr: 0x005BF7D0  thinker  cdecl; returns option index, -1 on failure
extern int  X_pop_6(const char* label, int flags, void* fn);       // addr: 0x005BF3F0  thinker  cdecl; script popup by label (#RULES / #GOVOPTIONS checkbox lists)
extern int  DialogChoices;                                        // addr: 0x009BC06C  thinker  checkbox-list popup state bitmask (callers store it before X_pop_6)
extern int  X_pops_18(const char* file, const char* label, int a3, char* a4, int flags, void* sprite, int x, int y, void* fn); // addr: 0x005BF930  thinker  cdecl; SCRIPT tries the alien files first
extern int  pops_18(const char* file, const char* label, int a3, char* a4, int flags, void* sprite, int x, int y, void* fn); // addr: 0x006276A0  thinker  cdecl; object = [g_pops_basepop_ext] unless it is visible, then [g_pops_basepop]
extern int  X_pop(const char* label, void* fn);                      // addr: 0x005BF310  thinker  cdecl; -> X_pop_9(0x9B8AA8,label,-1,0,0,fn); flags 0 = ordinary popup
extern int  X_pop_9(const char* file, const char* label, int a3, char* a4, int flags, void* fn); // addr: 0x005BF480  thinker  cdecl
extern int  pop_9(const char* file, const char* label, int a3, const char* a4, int flags, void* fn); // addr: 0x006272C0  thinker  cdecl; -> pops_18(...,flags,0,1,1,fn)
extern void pops_set_loc(int x, int y);                              // addr: 0x00627110  observed  cdecl; arms g_pops_loc_x/y for the next pops_18 set_loc; unreferenced in this exe
extern int  g_pops_loc_x;                                            // addr: 0x006973DC  observed  pops_18 set_loc x (reset to 0x2000 after use)
extern int  g_pops_loc_y;                                            // addr: 0x006973E0  observed  pops_18 set_loc y (reset to 0x2000 after use)
extern void tech_achieved(int faction, int tech, int a3, int a4);    // addr: 0x005BB000  thinker  cdecl; X_pop("ASKSEEDESIGN") @0x5BBCFA/0x5BBD6E -> design_new_veh
extern void design_new_veh(int a1, int a2);                          // addr: 0x00583CB0  thinker  cdecl
extern int  diplo_second_faction;                                    // addr: 0x0093F7CC  thinker  the faction that speaks
extern int  whose_territory(int faction, int x, int y, int* base, int flag); // addr: 0x004E3EF0  thinker  cdecl
extern int  base_find_2(int x, int y, int faction);                  // addr: 0x004E3C60  thinker  cdecl; nearest own base or -1
extern int  DirDX[9];                                                // addr: 0x0066EF50  observed  step x offsets by direction
extern int  DirDY[9];                                                // addr: 0x0066EF74  observed  step y offsets by direction
// field: VEH +0x00 int16_t x ; +0x02 int16_t y ; +0x08 uint16_t flags ; +0x0A int16_t unit_id ; +0x0E uint8_t faction_id ; +0x11 int8_t order
// field: VEH +0x30 int16_t next_veh_id_stack ; +0x32 int16_t prev_veh_id_stack
// field: MAP +0x02 uint8_t owner_nibble   low 4 bits = owner of units on the tile
// field: MAP +0x04 uint8_t visibility   per-faction bitmask
// field: MAP +0x07 int8_t territory_owner
// field: MAP +0x08 uint32_t flags   bit0 base in tile, bit1 unit in tile
extern int  stack_fix(int veh_id);                                   // addr: 0x005B8E10  thinker  cdecl; returns the stack's representative unit
extern void wake_stack(int veh_id);                                  // addr: 0x005B6060  thinker  cdecl; wakes order-1 units in the stack
extern struct BASE Bases[512];                                       // addr: 0x0097D040  thinker  stride 0x134
extern int  BaseCount;                                               // addr: 0x009A64CC  thinker
// field: BASE +0x00 int16 x
// field: BASE +0x02 int16 y
// field: BASE +0x04 uint8 faction_id
// field: BASE +0x06 int8 pop_size
// field: BASE +0x7C int32 specialist_total
// field: BASE +0x8C uint8 facilities_built[12]   bit = facility id (23 = Punishment Sphere, 41 = Geosynchronous Survey Pod)
// field: BASE +0x118 int32 talent_total
// field: BASE +0x11C int32 drone_total   includes superdrones
// field: BASE +0x120 int32 superdrone_total
extern int  is_sensor(int x, int y);                                 // addr: 0x005BF010  thinker  cdecl; 1 = sensor on tile; 2 = Geosync Survey Pod base tile or its dx,dy in {0,2} ring
extern struct Faction Factions[8];                                   // addr: 0x0096C9E0  thinker  stride 0x20CC
extern struct UNIT Units[];                                          // addr: 0x009AB868  thinker  stride 0x34
extern struct CChassis Chassis[];                                    // addr: 0x0094A330  thinker  stride 0x90
extern uint8_t FactionStatus[2];                                     // addr: 0x009A64E8  thinker  byte0 human mask, byte1 alive mask
// field: Faction +0x18 uint32_t diplo_status[8]   bit0 pact, bit1 treaty, bit2 truce, bit3 commlink
// field: UNIT +0x20 uint32_t ability_flags   0x2 deep radar, 0x4 cloaked, 0x40 deep pressure hull
// field: UNIT +0x24 uint8_t chassis_id ; +0x28 uint8_t carry_capacity
// field: CChassis +0x49 uint8_t triad   0 land, 1 sea, 2 air
// field: VEH +0x04 uint32_t state ; +0x14 int16_t waypoint_x[4] ; +0x1C int16_t waypoint_y[4]
// field: VEH +0x12 uint8_t waypoint_count   fixed waypoints (slot[count] = destination); state 0x2000000 = collecting
// field: VEH +0x13 uint8_t waypoint_aux   zeroed when collecting starts
// field: MAP +0x08 uint32_t flags   bit31 sensor array
extern struct VEH Vehs[];                                            // addr: 0x00952828  thinker  stride 0x34
extern int  VehCount;                                                // addr: 0x009A64C8  thinker
extern struct MAP* MapTiles;                                         // addr: 0x0094A30C  thinker  stride 0x2C; index y*MapHalfX + (x>>1)
extern int  MapHalfX;                                                // addr: 0x0068FAF0  thinker

// ==== Turn / game flow (control_game / control_turn; the update prompt's gates) ====
extern void control_game(void);                                      // addr: 0x0052AA30  thinker  cdecl; WinMain body: top_menu/desktop_init/control_turn loop; exits when ControlTurnB==0
extern void control_turn(void);                                      // addr: 0x005275B0  thinker  cdecl; single-player turn loop `while(ControlTurnA==0)`
extern void net_control_turn(void);                                  // addr: 0x0052A2E0  thinker  cdecl; multiplayer turn loop
extern void turn_upkeep(void);                                       // addr: 0x005258C0  thinker  cdecl; increments CurrentTurn @0x525ADC
extern int  CurrentTurn;                                             // addr: 0x009A64D4  thinker  turn counter
extern int  ControlTurnA;                                            // addr: 0x009B2068  thinker  1 = leave the turn loops (quit/retire/return to menu)
extern int  ControlTurnB;                                            // addr: 0x0093A948  thinker  1 = after leaving, return to the main menu instead of exiting
extern int  ControlTurnMove;                                         // addr: 0x009B2070  thinker  resume-turn faction (set on load); Console_human_turn zeroes it
extern int  GameHalted;                                              // addr: 0x0068F21C  thinker  1 = main menu / setup, 0 = game running
extern int  PbemActive;                                              // addr: 0x0093A95C  thinker  hotseat/PBEM flag
extern int  GameRules;                                               // addr: 0x009A649C  thinker  rules bits; 0x400 = RULES_IRONMAN
extern int  SaveFileMenu;                                            // addr: 0x00945D78  thinker  set around load_game from top_menu
extern void game_close(int a1);                                      // addr: 0x0058F430  thinker  cdecl; stop_timers + labels/Strings shutdown (Thinker 5.5 write_jumps here)
extern void system_close(void);                                      // addr: 0x0058F250  thinker  cdecl; release_sound, backbuffer, Console_close, Path/map shutdown
extern void desktop_close(void);                                     // addr: 0x0058EFF0  thinker  cdecl
extern int  desktop_init(int a1);                                    // addr: 0x0058EE60  thinker  cdecl; builds all in-game windows incl. PrefWin_build
extern int  map_menu(int quick);                                     // addr: 0x0058D6B0  thinker  cdecl; MAPMENU strip via SetupWin_do_menu_2 @0x58D74E
extern int  BasePop_exec_3(struct BasePop* self, int a2, void* fn);  // addr: 0x00602600  thinker  thiscall; Win_set_modal(flag,fn,0); returns [+0xA40] reply, or -1 (flags&0x40 / callback abort)
extern void BasePop_on_button_clicked(struct BasePop* self, int btn_id); // addr: 0x00604300  thinker  thiscall; vtbl+0xB0; [+0xA40]=selected id; cancel -> -1 iff flags&0x40; releases modal
extern int  BasePop_on_modal(void);                                  // addr: 0x00604A80  thinker  vtbl+0xEC of the Popup family; returns [0x9B8CFC]==0
extern int  Buffer_get_pcx_dimensions(const char* name, int* w, int* h); // addr: 0x005E2480  thinker  cdecl; 0 ok, 6 = file not found (filefind_get then CWD CreateFileA), 3 = not a PCX
extern int  Sprite_init(struct Sprite* self, const char* name, int w, int h); // addr: 0x005E3890  thinker  thiscall; filename-backed sprite (lazy load at blit)
extern char* filefind_get(const char* name);                         // addr: 0x006005D0  thinker  cdecl; resolves via [0x9B8298], [0x9B8498], [0x9B8198]; 0 = not found
extern int  text_open(char* filename, char* label);                  // addr: 0x005FD550  thinker  cdecl; appends .txt when no '.', seeks to #label; nonzero = not found
extern int  g_pop_default_result;                                    // addr: 0x00696EC0  observed  = -1; BasePop_exec_3 result when the modal callback aborted
// field: BasePop +0xA40  int   result_reply    reply index returned by BasePop_exec_3
// field: BasePop +0xA44  int   default_sel     Popup_start a4; top_menu/map_menu overwrite with the remembered choice
// field: BasePop +0xA48  char* caption         #caption text pointer (0 when absent)
// field: BasePop +0x2118 struct Sprite art_sprite   #sprite target; [+0x2144] points here when loaded
// field: BasePop +0x2144 struct Sprite* art     0 = no art
// field: BasePop +0x30A8 uint  flags           BasePop_start/pops_18 flags copy (0x40 cancel->-1, 0x4000 no key, 0x400 no 3/2 xs bump)
// field: BasePop +0x3104 int   art_scale_num   pops_18 x arg
// field: BasePop +0x3108 int   art_scale_den   pops_18 y arg
// field: BasePop +0x30B4 int   placed_x        BasePop_exec_3 placed window x (from the +0x30F8 request)
// field: BasePop +0x30B8 int   placed_y        BasePop_exec_3 placed window y (from the +0x30FC request)
// field: BasePop +0x30F8 int   loc_req_x       placement request: 0x1000 centre, <0 far-edge gap, else literal (set_loc / #x)
// field: BasePop +0x30FC int   loc_req_y       placement request y (set_loc / #y); 0x2000 = keep

// ==== Map effects: boom / Planet Buster ====
extern int  planet_busting(int a1, int a2, int a3);                // addr: 0x00500B60  thinker   cdecl
extern int  boom(int a1, int a2, int a3);                          // addr: 0x00504AA0  thinker   cdecl; explosion / Planet Buster animation on the map
extern void* g_pb_flic;                                            // addr: 0x0090EA68  observed  Flic playing buster.flc
extern struct Buffer g_pb_buffer;                                  // addr: 0x00915068  observed  300x248 buster.flc frame Buffer
extern int32_t g_pb_reactor;                                       // addr: 0x0090F7D4  observed  Planet Buster reactor 1..4; indexes boom's cloud-scale tables
extern struct Sprite g_expl_sprites_xi[];                          // addr: 0x007A9B30  observed  explosion frames cut from XI.pcx (0x2C-byte Sprites)
extern struct Sprite g_expl_sprites_xf[];                          // addr: 0x007AB460  observed  explosion frames cut from XF.pcx (0x2C-byte Sprites)
