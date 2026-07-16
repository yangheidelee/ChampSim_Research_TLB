#ifndef PREFETCHER_STLB_ATP_H
#define PREFETCHER_STLB_ATP_H

#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>

#include "modules.h"

// ATP implements the Agile TLB Prefetcher (ATP) from ISCA 2021 and sends
// selected candidates through ChampSim's STLB-local prefetch path. The JSON
// destination setting decides whether completed translations fill the STLB or
// the independent prefetch buffer.
class atp : public champsim::modules::stlb_prefetcher
{
public:
  struct statistics {
    uint64_t feedback_events = 0;
    uint64_t demand_miss_events = 0;
    uint64_t useful_prefetch_hit_events = 0;
    uint64_t prefetch_buffer_hit_events = 0;
    uint64_t ordinary_hit_events_ignored = 0;

    uint64_t h2p_fpq_hits = 0;
    uint64_t masp_fpq_hits = 0;
    uint64_t stp_fpq_hits = 0;

    uint64_t disabled_selections = 0;
    uint64_t h2p_selections = 0;
    uint64_t masp_selections = 0;
    uint64_t stp_selections = 0;

    uint64_t h2p_raw_candidates = 0;
    uint64_t h2p_candidates = 0;
    uint64_t masp_raw_candidates = 0;
    uint64_t masp_candidates = 0;
    uint64_t stp_raw_candidates = 0;
    uint64_t stp_candidates = 0;
    uint64_t invalid_candidate_drops = 0;
    uint64_t current_vpn_drops = 0;
    uint64_t duplicate_candidate_drops = 0;

    uint64_t h2p_fpq_insertions = 0;
    uint64_t h2p_fpq_duplicates = 0;
    uint64_t h2p_fpq_evictions = 0;
    uint64_t masp_fpq_insertions = 0;
    uint64_t masp_fpq_duplicates = 0;
    uint64_t masp_fpq_evictions = 0;
    uint64_t stp_fpq_insertions = 0;
    uint64_t stp_fpq_duplicates = 0;
    uint64_t stp_fpq_evictions = 0;

    uint64_t h2p_submitted = 0;
    uint64_t h2p_accepted = 0;
    uint64_t h2p_rejected = 0;
    uint64_t masp_submitted = 0;
    uint64_t masp_accepted = 0;
    uint64_t masp_rejected = 0;
    uint64_t stp_submitted = 0;
    uint64_t stp_accepted = 0;
    uint64_t stp_rejected = 0;

    uint64_t masp_table_lookups = 0;
    uint64_t masp_table_hits = 0;
    uint64_t masp_table_misses = 0;
    uint64_t masp_table_replacements = 0;
  };

private:
  static constexpr std::size_t FPQ_SIZE = 16;
  static constexpr std::size_t MAX_CANDIDATES = 4;
  static constexpr std::size_t MASP_TABLE_SETS = 16;
  static constexpr std::size_t MASP_TABLE_WAYS = 4;

  static constexpr uint16_t ENABLE_PREF_INITIAL = 127;
  static constexpr uint16_t ENABLE_PREF_MAXIMUM = 255;
  static constexpr uint16_t ENABLE_PREF_THRESHOLD = 128;
  static constexpr uint16_t SELECT_1_INITIAL = 31;
  static constexpr uint16_t SELECT_1_MAXIMUM = 63;
  static constexpr uint16_t SELECT_1_THRESHOLD = 32;
  static constexpr uint16_t SELECT_2_INITIAL = 1;
  static constexpr uint16_t SELECT_2_MAXIMUM = 3;
  static constexpr uint16_t SELECT_2_THRESHOLD = 2;

  enum selected_prefetcher {
    DISABLED,
    H2P,
    MASP,
    STP,
  };

  struct candidate_list {
    std::array<uint64_t, MAX_CANDIDATES> values{};
    std::size_t count = 0;
    uint64_t raw_count = 0;
    uint64_t invalid_drops = 0;
    uint64_t current_vpn_drops = 0;
    uint64_t duplicate_drops = 0;
  };

  class fake_prefetch_queue
  {
    std::deque<uint64_t> entries_{};

  public:
    void clear();
    bool consume(uint64_t vpn);
    void insert(uint64_t vpn, bool& duplicate, bool& eviction);
    std::size_t size() const;
  };

  struct masp_entry {
    bool valid = false;
    uint64_t pc = 0;
    uint64_t previous_miss_vpn = 0;
    int64_t stored_stride = 0;
    bool stride_valid = false;
    uint64_t last_used = 0;
  };

  statistics stats_{};

  uint16_t enable_pref_ = ENABLE_PREF_INITIAL;
  uint16_t select_1_ = SELECT_1_INITIAL;
  uint16_t select_2_ = SELECT_2_INITIAL;

  fake_prefetch_queue h2p_fpq_{};
  fake_prefetch_queue masp_fpq_{};
  fake_prefetch_queue stp_fpq_{};

  uint64_t h2p_previous_miss_vpn_ = 0;
  int64_t h2p_previous_distance_ = 0;
  bool h2p_previous_miss_valid_ = false;
  bool h2p_previous_distance_valid_ = false;

  std::array<std::array<masp_entry, MASP_TABLE_WAYS>, MASP_TABLE_SETS> masp_table_{};
  uint64_t masp_timestamp_ = 0;

  static void increment_counter(uint16_t& counter, uint16_t maximum);
  static void decrement_counter(uint16_t& counter);
  static int64_t vpn_distance(uint64_t current, uint64_t previous);
  static bool add_vpn_delta(uint64_t vpn, int64_t delta, uint64_t& target);

  void add_candidate(candidate_list& candidates, uint64_t current_vpn, int64_t delta) const;
  candidate_list generate_h2p_candidates(uint64_t current_vpn);
  candidate_list generate_masp_candidates(uint64_t current_vpn, uint64_t pc, bool record_statistics);
  candidate_list generate_stp_candidates(uint64_t current_vpn) const;

  masp_entry* find_masp_entry(uint64_t pc);
  masp_entry* allocate_masp_entry(uint64_t pc, bool& replacement);
  void touch_masp_entry(masp_entry& value);

  void update_counters(bool h2p_hit, bool masp_hit, bool stp_hit);
  selected_prefetcher select_prefetcher() const;

  void record_candidate_statistics(const candidate_list& h2p_candidates, const candidate_list& masp_candidates,
                                   const candidate_list& stp_candidates);
  void update_h2p_fpq(const candidate_list& candidates, bool record_statistics);
  void update_masp_fpq(const candidate_list& candidates, bool record_statistics);
  void update_stp_fpq(const candidate_list& candidates, bool record_statistics);
  void issue_selected_candidates(selected_prefetcher selected, const candidate_list& h2p_candidates, const candidate_list& masp_candidates,
                                 const candidate_list& stp_candidates, const champsim::modules::stlb_prefetcher_context& context,
                                 bool record_statistics);
  void issue_candidates(selected_prefetcher selected, const candidate_list& candidates,
                        const champsim::modules::stlb_prefetcher_context& context, bool record_statistics);

public:
  using champsim::modules::stlb_prefetcher::stlb_prefetcher;

  void stlb_prefetcher_initialize();
  void stlb_prefetcher_operate(const champsim::modules::stlb_prefetcher_context& context);
  void stlb_prefetcher_final_stats();

  const statistics& get_statistics() const;
};

#endif
