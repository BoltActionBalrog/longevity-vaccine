// prax.dll (PRACX 1.11, imagebase 0x10000000) symbols. Same line format as terranx.h. Names = PRACX source (refs\pracx).

// ==== Window / video mode ====
extern void SetWindowed(bool windowed);        // addr: 0x10009F60  observed  cdecl; posts WM_USER+3 when going windowed
extern void SetVideoMode();                    // addr: 0x10009ED0  observed  cdecl; ChangeDisplaySettings when ScreenSize != desktop
extern void RestoreVideoMode();                // addr: 0x10009940  observed  cdecl
extern bool m_fWindowed;                       // addr: 0x1004809C  observed  gates the stretch present + mouse mapping
extern bool m_fPlayingMovie;                   // addr: 0x1004809E  observed  SetWindowed refuses while set
extern RECT m_rWindowedRect;                   // addr: 0x100480A0  observed  WINDOWPLACEMENT.rcNormalPosition of the windowed state
extern bool SetWindowed_fInitialized;          // addr: 0x10049FFC  observed  function-static
extern struct CAC* m_pAC;                      // addr: 0x100470E4  observed  exe address table; +8 = HWND* phWnd
extern int  m_ptScreenSize_x;                  // addr: 0x10048D80  observed  [PRACX] ScreenWidth
