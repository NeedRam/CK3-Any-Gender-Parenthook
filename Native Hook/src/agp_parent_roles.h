#pragma once

#include <vector>

#include "agp_patch_runtime.h"

namespace agp {

struct ParentRoleReconstructionPlan {
	std::vector<std::uint8_t*> matches;
};

bool PrepareParentRoleReconstruction(const TextSection& text, ParentRoleReconstructionPlan* plan);
bool ApplyParentRoleReconstruction(const ParentRoleReconstructionPlan& plan);

} // namespace agp
