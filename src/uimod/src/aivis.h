// uimod AI perception filter -- the AI no longer knows where cloaked / deep-pressure-hull /
// scenario-invisible units are unless it has actually spotted them. See aivis.cpp.
#pragma once

// Install the hooks. Call once from Init(). Touches no patcher artifact (works on the PRACX-patched
// and the unpatched exe alike); every site is byte-checked and the feature self-disables on a mismatch.
void InstallAiVisibility();

// The LOCAL setting ([UIMod] AiRespectsCloak in Alpha Centauri.ini; default 1). In a network game the
// host's value, carried in its NEXT-UPKEEP broadcast, overrides this for the session.
int  AiVisGetLocal();
void AiVisSetLocal(int on);      // live-apply (no persist)
void AiVisSaveLocal();           // persist the current local value
constexpr int kAiVisDefault = 1;

// "Cloaked Transport Hides Its Cargo" ([UIMod] CloakedTransportHidesCargo; default 1): the engine reveals a
// hidden stack that holds more than one unit; with this on, units loaded in a cloaked / deep-pressure-hull
// transport are not counted, so the transport and its cargo are spotted (or not) as a single unit. Changes
// spotting for every observer; in a network game the host's value applies.
int  AiVisGetCargoOne();
void AiVisSetCargoOne(int on);   // live-apply (no persist)
void AiVisSaveCargoOne();
constexpr int kCargoOneDefault = 1;

// "Show Alert Icon on Detected Cloaked Units" ([UIMod] CloakAlertIcon; default 1): the red exclamation mark on
// the unit flag -- your own cloaked units another faction has spotted, and foreign cloaked units you have.
// Display only: nothing to agree on in network games.
int  AiVisGetMark();
void AiVisSetMark(int on);       // live-apply (no persist)
void AiVisSaveMark();
constexpr int kCloakMarkDefault = 1;

// "Air Drops Divert Around Unseen Defenders" ([UIMod] AirdropDiversion; default 1; a top-level row, not under the
// cloak parent: it covers fog of war too). A combat unit air-dropped onto a stack its faction cannot see lands on a
// free neighbouring square and reveals the stack, instead of the base game's refusal that gave the stack away. It
// changes how a drop resolves for every faction, so a network game follows the host's value.
int  AiVisGetAirdrop();
void AiVisSetAirdrop(int on);    // live-apply (no persist)
void AiVisSaveAirdrop();
constexpr int kAirdropDivertDefault = 1;

// ---- for the Thinker half (thinkeraivis.cpp) -------------------------------------------------------
bool  AiVisCoreInstalled();                 // the engine half (filter sites) installed
void  AiVisThinkerHalfInstalled();          // thinkeraivis.cpp: the Thinker half is in (pinned build only)
bool  AiVisForcedOff();                     // the filter cannot be in force this session, whatever the checkbox says
bool  AiVisAirdropInstalled();              // the air-drop diversion's detour is in (not under an unsupported Thinker)
bool  AiVisFactionFiltered(int f);          // the setting in force says ON and f is an AI faction the filter applies to
bool  AiVisHiddenStack(int vehId, int f);   // the stack holding vehId is hidden from f (the user's rule; see aivis.cpp)
bool  AiVisTileHidden(int x, int y, int f); // the stack on (x, y) is hidden from f; false for an empty tile
int   AiVisBump(int veh, int dir);          // a filtered AI unit stepping into an unseen hidden stack: spot it and clear the
                                            // order; 1 = handled (the caller returns 0 from order_veh), 0 = proceed
void* AiVisEnemyMoveWrapper();              // the viewer-setting wrapper around the engine's enemy_move
void* AiVisAirdropWrapper();                // the airdrop-diversion wrapper (cdecl veh, tx, ty, flags), for a detour on
                                            // Thinker's own action_airdrop
void  AiVisAirdropSetNext(void* next);      // the function the wrapper continues to (Thinker's trampoline); arms the group
// ---- 1.0.1 groups (work\briefs\cloak-filter-1.0.1-spec.md); the Thinker halves in thinkeraivis.cpp call these ----
extern int g_aivisInDuel;                   // nonzero while a repaired bombard duel runs (the naked nerve gates read it)
void  __cdecl AiVisCombatReveal(int atk, int def);   // fix 1: mark a hidden attacker's stack for the defender
bool  AiVisBombardSkip(int stack, int actor, int owner);   // fix 2 + the non-war skip: the scan must not see
                                                     // this stack (owner = the scan's type-15 territory owner, -1 = any)
void  AiVisDuelRecord(int veh);                      // fix 3: the firer's moves before the bombard's veh_skip
bool  AiVisDuelActive();                             // fix 3: the duel repair is on (bit 8, installed)
int   AiVisDuelRun(int veh, int offset, int a3, int a4, int a5, void* next);   // fix 3, Thinker parity (BLOCK marks moved)
int   AiVisAskHasty(int atk, int f, int local, int ctype, int movesLeft, int defUnit);   // fix 4: 1 = cancel
int*  AiVisAskHastyMark();                           // fix 4: the one-shot mark (1 = Long Range Fire, 2 = redirect)
void  AiVisSetThinkerGroups(bool reveal, bool bombard, bool duel, bool ask);   // the Thinker halves that installed
void  __cdecl AiVisOnGameStart(unsigned ret);        // desktop_init (prefs.cpp's build hook; ret = its return address):
                                                     // forget the last session's masks at a real game start / load
int   AiVisZocAdjust(int kind, int r, int x, int y, int f);   // zone of control, the hidden-unit exemption: `r` is the original
                                            // zoc function's answer (kind 0 = zoc_any, 1 = zoc_veh, 2 = zoc_sea semantics);
                                            // a nonzero r is recomputed without the human factions' unseen hidden units
                                            // when the setting is on (aivis.cpp ZocAdjust). Rides the cloak setting's own
                                            // net bit: nothing has shipped with that bit yet, so peers agree (audit 2026-10-30)
