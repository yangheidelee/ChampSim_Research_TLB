#ifndef TLB_PREFETCH_METADATA_H
#define TLB_PREFETCH_METADATA_H

#include <cstdint>

inline constexpr uint32_t L1D_PREF_META_VALID = 1u << 31;
inline constexpr uint32_t L1D_PREF_META_CROSS = 1u << 30;
inline constexpr uint32_t L1D_PREF_META_TRANSLATION_ONLY = 1u << 29;
// Keep the established vBerti metadata mask unchanged. The translation-only
// bit is an orthogonal runtime-mode marker and is managed explicitly.
inline constexpr uint32_t L1D_PREF_META_MASK = L1D_PREF_META_VALID | L1D_PREF_META_CROSS;

inline bool is_l1d_pref_meta(uint32_t meta) { return (meta & L1D_PREF_META_VALID) != 0; }

inline bool is_l1d_pref_cross(uint32_t meta) { return (meta & L1D_PREF_META_CROSS) != 0; }

inline bool is_l1d_pref_translation_only(uint32_t meta) { return (meta & L1D_PREF_META_TRANSLATION_ONLY) != 0; }

inline uint32_t mark_l1d_pref_translation_only(uint32_t meta) { return meta | L1D_PREF_META_TRANSLATION_ONLY; }

inline uint32_t clear_l1d_pref_translation_only(uint32_t meta) { return meta & ~L1D_PREF_META_TRANSLATION_ONLY; }

inline uint32_t make_l1d_pref_meta(uint32_t meta, bool cross_page)
{
  auto result = (meta & ~L1D_PREF_META_MASK) | L1D_PREF_META_VALID;
  if (cross_page)
    result |= L1D_PREF_META_CROSS;
  return result;
}

#endif
