// End-to-end harness for uimod portrait_files.cpp (tests\test_portrait_files.py): the REAL lookup + WIC decode,
// run from a throwaway folder laid out like a game directory (the exe's own folder is the "game dir").
//   portrait_decode_selftest <name> [nopack|off]  -> "none" | "<w> <h> <r> <g> <b>" (after pre-reduce, pixel (0,0))
//   nopack = "Use Turovetsky's HD Portrait Pack" off; off = "Enable Custom Portraits" off
#include "../../src/uimod/src/portrait_files.cpp"
#include <cstdio>
#include <cstring>

#pragma comment(lib, "windowscodecs.lib")
#pragma comment(lib, "ole32.lib")

void UimodLog(const char* msg) { std::fputs(msg, stderr); }

int main(int argc, char** argv)
{
    if (argc != 2 && argc != 3) return 2;
    if (argc == 3) {
        if (std::strcmp(argv[2], "nopack") == 0) portrait_files::SetOptions(true, false);
        else if (std::strcmp(argv[2], "off") == 0) portrait_files::SetOptions(false, true);
        else return 3;
    }
    auto img = portrait_files::Find(argv[1]);
    if (!img) { std::printf("none"); return 0; }
    std::printf("%d %d %d %d %d", img->w, img->h, img->rgb[0], img->rgb[1], img->rgb[2]);
    // a second lookup of the unchanged file must be the cached object
    auto again = portrait_files::Find(argv[1]);
    return again.get() == img.get() ? 0 : 4;
}
