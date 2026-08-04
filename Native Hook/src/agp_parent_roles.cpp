#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "agp_parent_roles.h"

#include <cstring>

namespace agp {
namespace {

const std::uint8_t reconcile_parent_roles[] = { 0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x00, 0x48, 0x8B, 0xD6, 0x48, 0x8B, 0xCB, 0x74, 0x07, 0xE8, 0x00, 0x00, 0x00, 0x00, 0xEB, 0x05, 0xE8, 0x00, 0x00, 0x00, 0x00, 0x48, 0x83, 0xC7, 0x04 };
const char reconcile_parent_roles_mask[] = "xxxxxxxxxxxxxxxx????xxx????xxxx";

bool HookParentRoleReconstruction(std::uint8_t* site) {
	// CK3 rebuilds each child's real parent slot from the reciprocal child list
	// after loading. Vanilla chooses father/mother solely from the parent's sex.
	// The explicit father and mother markers are stored in family_data + 8 and
	// +C respectively; use either marker before falling back to sex.
	auto* const base = reinterpret_cast<std::uint8_t*>(GetModuleHandleW(nullptr));
	auto* const set_real_father = base + 0x02607a90;
	auto* const set_real_mother = base + 0x02607c50;
	auto* const resume = site + 0x1b;
	auto* const stub = AllocateNear(site, 96);
	if (stub == nullptr || !IsRel32Reachable(stub + 47, set_real_mother) ||
		!IsRel32Reachable(stub + 52, resume) || !IsRel32Reachable(stub + 63, set_real_father) ||
		!IsRel32Reachable(stub + 68, resume)) {
		return false;
	}

	const std::uint8_t code[] = {
		0x48, 0x8B, 0x83, 0xA0, 0x01, 0x00, 0x00,
		0x48, 0x85, 0xC0,
		0x74, 0x0E,
		0x8B, 0x4E, 0x18,
		0x39, 0x48, 0x08,
		0x74, 0x20,
		0x39, 0x48, 0x0C,
		0x74, 0x0B,
		0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x00,
		0x74, 0x12,
		0xEB, 0x00,
		0x48, 0x8B, 0xD6,
		0x48, 0x8B, 0xCB,
		0xE8, 0x00, 0x00, 0x00, 0x00,
		0xE9, 0x00, 0x00, 0x00, 0x00,
		0x48, 0x8B, 0xD6,
		0x48, 0x8B, 0xCB,
		0xE8, 0x00, 0x00, 0x00, 0x00,
		0xE9, 0x00, 0x00, 0x00, 0x00
	};
	if (!WriteBytes(stub, code, sizeof(code))) {
		return false;
	}
	WriteRel32(stub + 43, set_real_mother);
	WriteRel32(stub + 48, resume);
	WriteRel32(stub + 59, set_real_father);
	WriteRel32(stub + 64, resume);
	FlushInstructionCache(GetCurrentProcess(), stub, sizeof(code));

	std::uint8_t jump[5] = { 0xE9, 0x00, 0x00, 0x00, 0x00 };
	const auto jump_displacement = static_cast<std::int32_t>(stub - (site + 5));
	std::memcpy(jump + 1, &jump_displacement, sizeof(jump_displacement));
	return WriteBytes(site, jump, sizeof(jump));
}

} // namespace

bool PrepareParentRoleReconstruction(const TextSection& text, ParentRoleReconstructionPlan* plan) {
	plan->matches = FindPattern(text, reconcile_parent_roles, reconcile_parent_roles_mask, sizeof(reconcile_parent_roles));
	if (plan->matches.size() != 1) {
		Log("AGP Parent Roles: reconstruction signature mismatch; no changes made.");
		return false;
	}
	return true;
}

bool ApplyParentRoleReconstruction(const ParentRoleReconstructionPlan& plan) {
	return HookParentRoleReconstruction(plan.matches[0]);
}

} // namespace agp
