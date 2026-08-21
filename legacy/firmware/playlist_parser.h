#pragma once
#include <string>
#include <vector>

#ifdef __has_include
    #if __has_include("lvgl.h")
        #ifndef LV_LVGL_H_INCLUDE_SIMPLE
            #define LV_LVGL_H_INCLUDE_SIMPLE
        #endif
    #endif
#endif

#if defined(LV_LVGL_H_INCLUDE_SIMPLE)
    #include "lvgl.h"
#else
    #include "lvgl/lvgl.h"
#endif

// -- Parse a JSON array of strings like ["name1","name2"] --
std::vector<std::string> parse_json_string_array(const std::string& json) {
    std::vector<std::string> result;
    std::string s = json;
    size_t pos = 0;

    // -- Find opening bracket --
    pos = s.find('[');
    if (pos == std::string::npos) return result;
    s = s.substr(pos + 1);

    while (true) {
        // -- Find opening quote --
        size_t start = s.find('"');
        if (start == std::string::npos) break;
        s = s.substr(start + 1);

        // -- Read chars until closing quote, handle escapes --
        std::string item;
        size_t i = 0;
        while (i < s.size()) {
            if (s[i] == '\\' && i + 1 < s.size()) {
                if (s[i+1] == '"')  item += '"';
                else if (s[i+1] == 'n')  item += '\n';
                else if (s[i+1] == '\\') item += '\\';
                else item += s[i+1];
                i += 2;
            } else if (s[i] == '"') {
                i++;
                break;
            } else {
                item += s[i];
                i++;
            }
        }
        result.push_back(item);
        s = s.substr(i);

        // -- Stop at closing bracket --
        size_t next = s.find_first_not_of(" ,\n\r\t");
        if (next != std::string::npos && s[next] == ']') break;
    }
    return result;
}