#include "stlb_ideal.h"

#include <algorithm>
#include <cctype>
#include <stdexcept>

stlb_ideal_mode champsim_stlb_ideal_mode = stlb_ideal_mode::OFF;
bool champsim_stlb_ideal_fill = false;

stlb_ideal_mode parse_stlb_ideal_mode(const std::string& text)
{
  auto lower = text;
  std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

  if (lower == "off" || lower == "none" || lower == "0")
    return stlb_ideal_mode::OFF;
  if (lower == "demand" || lower == "demand-only")
    return stlb_ideal_mode::DEMAND;
  if (lower == "l1pref" || lower == "l1-prefetch" || lower == "prefetch" || lower == "pref")
    return stlb_ideal_mode::L1_PREFETCH;
  if (lower == "all" || lower == "ideal")
    return stlb_ideal_mode::ALL;

  throw std::invalid_argument{"unknown STLB ideal mode: " + text};
}

const char* stlb_ideal_mode_name(stlb_ideal_mode mode)
{
  switch (mode) {
  case stlb_ideal_mode::OFF:
    return "off";
  case stlb_ideal_mode::DEMAND:
    return "demand";
  case stlb_ideal_mode::L1_PREFETCH:
    return "l1pref";
  case stlb_ideal_mode::ALL:
    return "all";
  }
  return "off";
}

bool stlb_ideal_resolves(stlb_ideal_mode mode, translation_origin origin)
{
  switch (mode) {
  case stlb_ideal_mode::OFF:
    return false;
  case stlb_ideal_mode::DEMAND:
    return origin == translation_origin::DEMAND_DATA || origin == translation_origin::DEMAND_INSTRUCTION;
  case stlb_ideal_mode::L1_PREFETCH:
    return origin == translation_origin::L1D_PREFETCH || origin == translation_origin::L1I_PREFETCH;
  case stlb_ideal_mode::ALL:
    return true;
  }
  return false;
}
