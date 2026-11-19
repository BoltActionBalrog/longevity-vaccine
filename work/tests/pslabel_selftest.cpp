// Self-test harness for pslabel_core.h (tests\test_pssphere_psych_label.py builds and runs it). One case per stdin line:
//   id staple sphereByte labelCount source
//   target b0 b1 b2 b3 b4 at opcode lo hi  -> pslabel::BranchTarget (all hex); prints the target in hex (0 = refused)
//   encode at opcode fn                    -> pslabel::EncodeBranch (hex); prints the 5 bytes in hex
// id = CurrentBaseID; staple / sphereByte go into that base's record (when id is 0..511); labelCount = TextLabels.count;
// source = a label index (the label's own pointer, as Strings_get hands it over), "c<index>" (a copy of its text at
// another address), "x" (text that is no label) or "null". Prints 1 (engine strcat), 0 (Thinker's function) or "bad".
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "../../src/uimod/src/pslabel_core.h"

namespace {

std::string LabelText(int i)
{
    switch (i) {
    case 322: return "Unmodified";
    case 323: return "Facilities";
    case 324: return "Police";
    case 327: return "Secret Projects";
    case 970: return "Captured Base";
    case 971: return "Stapled Base";
    default: return "label " + std::to_string(i);
    }
}

} // namespace

int main()
{
    std::vector<std::string> texts(1200);
    std::vector<const char*> labels(texts.size());
    for (size_t i = 0; i < texts.size(); ++i) { texts[i] = LabelText(static_cast<int>(i)); labels[i] = texts[i].c_str(); }
    std::vector<uint8_t> bases(pslabel::kMaxBases * pslabel::kBaseSize);
    std::string line;
    while (std::getline(std::cin, line)) {
        std::istringstream in(line);
        std::string head;
        {
            std::istringstream peek(line);
            peek >> head;
        }
        if (head == "target" || head == "encode") {
            in >> head >> std::hex;
            if (head == "target") {
                unsigned b[5]; unsigned long long at = 0, op = 0, lo = 0, hi = 0;
                if (!(in >> b[0] >> b[1] >> b[2] >> b[3] >> b[4] >> at >> op >> lo >> hi)) { std::puts("bad"); continue; }
                uint8_t bytes[5];
                for (int i = 0; i < 5; ++i) bytes[i] = static_cast<uint8_t>(b[i]);
                std::printf("%llx\n", static_cast<unsigned long long>(pslabel::BranchTarget(
                    bytes, static_cast<uintptr_t>(at), static_cast<uint8_t>(op), static_cast<uintptr_t>(lo), static_cast<uintptr_t>(hi))));
            } else {
                unsigned long long at = 0, op = 0, fn = 0;
                if (!(in >> at >> op >> fn)) { std::puts("bad"); continue; }
                uint8_t out[5];
                pslabel::EncodeBranch(out, static_cast<uintptr_t>(at), static_cast<uint8_t>(op), static_cast<uintptr_t>(fn));
                std::printf("%02x%02x%02x%02x%02x\n", out[0], out[1], out[2], out[3], out[4]);
            }
            continue;
        }
        int id = 0, staple = 0, sphere = 0;
        long long count = 0;
        std::string src;
        if (!(in >> id >> staple >> sphere >> count >> src) || count < 0 || count > static_cast<long long>(labels.size())) {
            std::puts("bad");
            continue;
        }
        std::fill(bases.begin(), bases.end(), 0);
        if (id >= 0 && id < pslabel::kMaxBases) {
            bases[id * pslabel::kBaseSize + pslabel::kBaseStaple] = static_cast<uint8_t>(staple);
            bases[id * pslabel::kBaseSize + pslabel::kBaseSphereByte] = static_cast<uint8_t>(sphere);
        }
        std::string copy;
        const char* source = nullptr;
        if (src == "null") source = nullptr;
        else if (src == "x") { copy = "Nothing"; source = copy.c_str(); }
        else if (src[0] == 'c') { copy = texts.at(std::stoi(src.substr(1))); source = copy.c_str(); }
        else source = labels.at(std::stoi(src));
        std::puts(pslabel::KeepOwn(id, bases.data(), labels.data(), static_cast<uint32_t>(count), source) ? "1" : "0");
    }
    return 0;
}
