// uimod.log redaction.  Players attach uimod.log to public bug reports, and a path under their profile folder
// (C:\Users\<account>\...) names their Windows account.  UimodLog passes every message through RedactProfile, so no
// module has to remember to.  Pure and header-only: work\tests\logredact_selftest.cpp tests it directly.
#pragma once

#include <string>

namespace logredact {

inline char Fold(char c)
{
    if (c >= 'A' && c <= 'Z') return static_cast<char>(c - 'A' + 'a');
    return c == '/' ? '\\' : c;                // Windows treats both separators alike
}

// A character that would continue a folder name: the match must end at a separator, a quote, a space or the end.
inline bool NameChar(char c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' || c == '_' ||
           c == '-' || static_cast<unsigned char>(c) >= 0x80;
}

// `line` with every occurrence of the profile folder replaced by %USERPROFILE% (compared as Windows compares paths:
// ASCII case and the two separators folded).  A profile shorter than "C:\x" or one ending in a separator is
// normalised first; a folder that merely starts with the profile's name (C:\Users\Ann vs C:\Users\Anna) is left.
inline std::string RedactProfile(const std::string& line, std::string profile)
{
    while (!profile.empty() && (profile.back() == '\\' || profile.back() == '/')) profile.pop_back();
    if (profile.size() < 4) return line;       // empty, or a bare drive: nothing account-specific to hide
    std::string out;
    out.reserve(line.size());
    size_t i = 0;
    while (i < line.size()) {
        bool hit = line.size() - i >= profile.size();
        for (size_t k = 0; hit && k < profile.size(); ++k) hit = Fold(line[i + k]) == Fold(profile[k]);
        if (hit && i + profile.size() < line.size() && NameChar(line[i + profile.size()])) hit = false;
        if (hit) {
            out += "%USERPROFILE%";
            i += profile.size();
        } else {
            out += line[i++];
        }
    }
    return out;
}

}  // namespace logredact
