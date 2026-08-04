#pragma once

#include <cstdint>
#include <vector>

#include "agp_patch_runtime.h"

namespace agp {

struct FemaleFatherPatchPlan {
	std::vector<std::uint8_t*> runtime_rdi;
	std::vector<std::uint8_t*> runtime_rsi;
	std::vector<std::uint8_t*> runtime_rdi_patched;
	std::vector<std::uint8_t*> runtime_rsi_patched;
	std::vector<std::uint8_t*> pregnancy_a;
	std::vector<std::uint8_t*> pregnancy_b;
	std::vector<std::uint8_t*> pregnancy_a_patched;
	std::vector<std::uint8_t*> pregnancy_b_patched;
	std::vector<std::uint8_t*> real_father_validation;
	std::vector<std::uint8_t*> real_father_write;
};

bool PrepareFemaleFatherPatch(const TextSection& text, FemaleFatherPatchPlan* plan);
bool ApplyFemaleFatherPatch(const FemaleFatherPatchPlan& plan);

} // namespace agp
