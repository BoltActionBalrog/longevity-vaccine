REPLACEMENT PORTRAITS -- Longevity Vaccine
==========================================

Put your own leader or native-life portraits in this folder and the game shows them instead of the
originals.

Name each image after the faction's file (the name of its .pcx in the game folder):

    gaians.png      Lady Deirdre Skye            cyborg.png      Prime Function Aki Zeta-5
    hive.png        Chairman Sheng-ji Yang       pirates.png     Captain Ulrik Svensgaard
    univ.png        Provost Prokhor Zakharov     drone.png       Foreman Domai
    morgan.png      CEO Nwabudike Morgan         angels.png      Datatech Sinder Roze
    spartans.png    Colonel Corazon Santiago     fungboy.png     Prophet Cha Dawn
    believe.png     Sister Miriam Godwinson      caretake.png    Guardian Lular H'minee
    peace.png       Commissioner Pravin Lal      usurper.png     Conqueror Judaa Marr

    BTwrm.png  Mind Worms      BTisl.png  Isle of the Deep     BTchi.png       Locusts of Chiron
    BTsealrk.png  Sealurk      BTsporlnch.png  Spore Launcher  BTfungtow.png   Fungal Tower

A custom or Thinker faction works the same way: use its file name.  Two factions that share one
.pcx also share one portrait.

FORMAT
  .png or .jpg, 32 to 2048 pixels on each side, at most 32 MB.  Best: about 1120 x 1350 (the
  portrait slots are about 0.83 wide for each 1 tall).  A different shape is cropped to fit,
  centred left-to-right and a little high top-to-bottom; it is never stretched.  Transparency is
  ignored.

WHICH FILE WINS
  For each portrait the game uses the first of these that exists and can be read:
    1. portraits\<name>.png   2. portraits\<name>.jpg   3. the game's original portrait

  "Enable User Portraits" OFF: the game's original portraits everywhere.

WHEN CHANGES SHOW
  Leaders: the next time the factions are loaded (start or load a game), or at once when you
  change one of the portrait settings below.  Native life: at its next combat.

SETTINGS
  Preferences > Longevity Mod Preferences: "Enable User Portraits" turns all of this on or off;
  under it, "Add Scanlines".  Scanlines apply to replacement images only; the game's own
  portraits are unchanged.  Changes take effect at once and are saved with OK.

If an image cannot be used, the original portrait is shown and the reason is written to uimod.log
in the game folder.
