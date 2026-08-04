#pragma once

#include <cstdint>
#include <vector>

#include "agp_patch_runtime.h"

namespace agp {

struct MaleMotherPatchPlan {
	std::vector<std::uint8_t*> runtime_rdi;
	std::vector<std::uint8_t*> runtime_rsi;
	std::vector<std::uint8_t*> runtime_rdi_patched;
	std::vector<std::uint8_t*> runtime_rsi_patched;
	std::vector<std::uint8_t*> pregnancy;
	std::vector<std::uint8_t*> pregnancy_patched;
	std::vector<std::uint8_t*> real_mother_validation;
	std::vector<std::uint8_t*> real_mother_validation_patched;
	std::vector<std::uint8_t*> real_mother_write;
};

bool PrepareMaleMotherPatch(const TextSection& text, MaleMotherPatchPlan* plan);
bool ApplyMaleMotherPatch(const MaleMotherPatchPlan& plan);

} // namespace agp
