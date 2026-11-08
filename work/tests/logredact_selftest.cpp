// Harness for src\uimod\src\logredact.h (driven by test_logredact.py).  Each stdin line is "<profile>\t<line>";
// each stdout line is RedactProfile(line, profile).
#include <iostream>
#include <string>

#include "../../src/uimod/src/logredact.h"

int main()
{
    std::string in;
    while (std::getline(std::cin, in)) {
        if (!in.empty() && in.back() == '\r') in.pop_back();
        const size_t tab = in.find('\t');
        const std::string profile = tab == std::string::npos ? std::string() : in.substr(0, tab);
        const std::string line = tab == std::string::npos ? in : in.substr(tab + 1);
        std::cout << logredact::RedactProfile(line, profile) << "\n";
    }
    return 0;
}
