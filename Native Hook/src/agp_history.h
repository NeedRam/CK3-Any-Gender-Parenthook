#pragma once

#include <cstdint>
#include <vector>

#include "agp_patch_runtime.h"

namespace agp {

struct HistoryPatchPlan {
	std::vector<std::uint8_t*> original;
	std::vector<std::uint8_t*> already_patched;
};

bool PrepareHistoryPatch(const TextSection& text, HistoryPatchPlan* plan);
bool ApplyHistoryPatch(const HistoryPatchPlan& plan);

} // namespace agp
