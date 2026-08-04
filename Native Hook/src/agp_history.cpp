#include "agp_history.h"

#include <cstring>

namespace agp {
namespace {

bool HookHistoryGenderCheck(std::uint8_t* check) {
	// The history loader uses one common validation branch for father and mother
	// relations. Unlike the runtime effects, its expected-gender value is not
	// encoded in a distinct nearby branch. Replacing only its conditional jump
	// avoids a fragile trampoline during initial history loading.
	const auto original_jump_displacement = *reinterpret_cast<std::int32_t*>(check + 9);
	auto* const valid_parent = check + 13 + original_jump_displacement;
	if (!IsRel32Reachable(check + 12, valid_parent)) {
		return false;
	}
	std::uint8_t unconditional_jump[6] = { 0xE9, 0x00, 0x00, 0x00, 0x00, 0x90 };
	const auto delta = valid_parent - (check + 12);
	const auto displacement = static_cast<std::int32_t>(delta);
	std::memcpy(unconditional_jump + 1, &displacement, sizeof(displacement));
	return WriteBytes(check + 7, unconditional_jump, sizeof(unconditional_jump));
}

const std::uint8_t history_check[] = { 0x44, 0x38, 0xA7, 0x99, 0x01, 0x00, 0x00, 0x0F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x49, 0x8B, 0x4E, 0x10 };
const char history_mask[] = "xxxxxxxxx????xxxx";
const std::uint8_t history_already_patched[] = { 0x44, 0x38, 0xA7, 0x99, 0x01, 0x00, 0x00, 0xE9, 0x00, 0x00, 0x00, 0x00, 0x90, 0x49, 0x8B, 0x4E, 0x10 };
const char history_already_patched_mask[] = "xxxxxxxx?????xxxx";

} // namespace

bool PrepareHistoryPatch(const TextSection& text, HistoryPatchPlan* plan) {
	plan->original = FindPattern(text, history_check, history_mask, sizeof(history_check));
	plan->already_patched = FindPattern(text, history_already_patched, history_already_patched_mask, sizeof(history_already_patched));
	if (plan->original.size() + plan->already_patched.size() != 1) {
		Log("AGP History: signature mismatch; no changes made.");
		return false;
	}
	return true;
}

bool ApplyHistoryPatch(const HistoryPatchPlan& plan) {
	return plan.original.empty() || HookHistoryGenderCheck(plan.original[0]);
}

} // namespace agp
