#pragma once

#include <cstdint>

#include "agp_patch_runtime.h"

namespace agp {

struct CloseFamilyPatchPlan {
	std::uint8_t* helper;
};

bool PrepareCloseFamilyPatch(const TextSection& text, CloseFamilyPatchPlan* plan);
bool ApplyCloseFamilyPatch(const CloseFamilyPatchPlan& plan);

} // namespace agp
