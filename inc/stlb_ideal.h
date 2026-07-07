#ifndef STLB_IDEAL_H
#define STLB_IDEAL_H

#include <string>

#include "access_type.h"

enum class stlb_ideal_mode : unsigned {
  OFF = 0,
  DEMAND,
  L1_PREFETCH,
  ALL,
};

extern stlb_ideal_mode champsim_stlb_ideal_mode;
extern bool champsim_stlb_ideal_fill;

stlb_ideal_mode parse_stlb_ideal_mode(const std::string& text);
const char* stlb_ideal_mode_name(stlb_ideal_mode mode);
bool stlb_ideal_resolves(stlb_ideal_mode mode, translation_origin origin);

#endif
