#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "agp_female_father.h"

#include <cstring>

namespace agp {
namespace {

bool HookFemaleFatherPersistence(std::uint8_t* site) {
	// CK3 keeps a real-father pointer only while the game is running, then
	// serializes parentage from the reciprocal child list. Preserve a female
	// real father in the ordinary persisted father field as well. On load the
	// shared reconstruction hook restores the correct role from that marker.
	auto* const resume = site + 0x0d;
	auto* const stub = AllocateNear(site, 32);
	if (stub == nullptr || !IsRel32Reachable(stub + 30, resume)) {
		return false;
	}

	const std::uint8_t code[] = {
		0x8B, 0x46, 0x18,
		0x89, 0x42, 0x04,
		0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x00,
		0x74, 0x03,
		0x89, 0x42, 0x08,
		0x48, 0x8B, 0x87, 0xB8, 0x01, 0x00, 0x00,
		0xE9, 0x00, 0x00, 0x00, 0x00
	};
	if (!WriteBytes(stub, code, sizeof(code))) {
		return false;
	}
	WriteRel32(stub + 26, resume);
	FlushInstructionCache(GetCurrentProcess(), stub, sizeof(code));

	std::uint8_t jump[5] = { 0xE9, 0x00, 0x00, 0x00, 0x00 };
	const auto jump_displacement = static_cast<std::int32_t>(stub - (site + 5));
	std::memcpy(jump + 1, &jump_displacement, sizeof(jump_displacement));
	return WriteBytes(site, jump, sizeof(jump));
}

const std::uint8_t runtime_father_rdi[] = { 0x80, 0xBF, 0x99, 0x01, 0x00, 0x00, 0x00, 0x74, 0x00, 0x4C, 0x8D, 0x05, 0x00, 0x00, 0x00, 0x00, 0xC7, 0x85, 0x30, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xBA, 0x00, 0x02, 0x00, 0x00 };
const std::uint8_t runtime_father_rsi[] = { 0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x00, 0x74, 0x00, 0x4C, 0x8D, 0x05, 0x00, 0x00, 0x00, 0x00, 0xC7, 0x85, 0x30, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xBA, 0x00, 0x02, 0x00, 0x00 };
const std::uint8_t runtime_father_rdi_patched[] = { 0x80, 0xBF, 0x99, 0x01, 0x00, 0x00, 0x00, 0xEB, 0x00, 0x4C, 0x8D, 0x05, 0x00, 0x00, 0x00, 0x00, 0xC7, 0x85, 0x30, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xBA, 0x00, 0x02, 0x00, 0x00 };
const std::uint8_t runtime_father_rsi_patched[] = { 0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x00, 0xEB, 0x00, 0x4C, 0x8D, 0x05, 0x00, 0x00, 0x00, 0x00, 0xC7, 0x85, 0x30, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xBA, 0x00, 0x02, 0x00, 0x00 };
const char runtime_mask[] = "xxxxxxxx?xxx????xxxxxxxxxxxxxxx";

const std::uint8_t pregnancy_father_a[] = { 0x41, 0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x00, 0x0F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x48, 0x8D, 0x54, 0x24, 0x40, 0x49, 0x8B, 0xCE, 0xE8 };
const char pregnancy_father_a_mask[] = "xxxxxxxxxx????xxxxxxxxx";
const std::uint8_t pregnancy_father_a_patched[] = { 0x41, 0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x00, 0xE9, 0x00, 0x00, 0x00, 0x00, 0x90, 0x48, 0x8D, 0x54, 0x24, 0x40, 0x49, 0x8B, 0xCE, 0xE8 };
const char pregnancy_father_a_patched_mask[] = "xxxxxxxxx?????xxxxxxxxx";
const std::uint8_t pregnancy_father_b[] = { 0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x00, 0x0F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x48, 0x8D, 0x54, 0x24, 0x40, 0x48, 0x8B, 0xCE, 0xE8 };
const char pregnancy_father_b_mask[] = "xxxxxxxxx????xxxxxxxxx";
const std::uint8_t pregnancy_father_b_patched[] = { 0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x00, 0xE9, 0x00, 0x00, 0x00, 0x00, 0x90, 0x48, 0x8D, 0x54, 0x24, 0x40, 0x48, 0x8B, 0xCE, 0xE8 };
const char pregnancy_father_b_patched_mask[] = "xxxxxxxx?????xxxxxxxxx";

const std::uint8_t real_father_validation[] = { 0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x00, 0x0F, 0x85, 0x00, 0x00, 0x00, 0x00, 0x48, 0x3B, 0xF3, 0x0F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x48, 0x8B, 0x05 };
const char real_father_validation_mask[] = "xxxxxxxxx????xxxxx????xxx";
const std::uint8_t real_father_write[] = { 0x8B, 0x46, 0x18, 0x89, 0x42, 0x04, 0x48, 0x8B, 0x87, 0xB8, 0x01, 0x00, 0x00 };
const char real_father_write_mask[] = "xxxxxxxxxxxxx";

} // namespace

bool PrepareFemaleFatherPatch(const TextSection& text, FemaleFatherPatchPlan* plan) {
	plan->runtime_rdi = FindPattern(text, runtime_father_rdi, runtime_mask, sizeof(runtime_father_rdi));
	plan->runtime_rsi = FindPattern(text, runtime_father_rsi, runtime_mask, sizeof(runtime_father_rsi));
	plan->runtime_rdi_patched = FindPattern(text, runtime_father_rdi_patched, runtime_mask, sizeof(runtime_father_rdi_patched));
	plan->runtime_rsi_patched = FindPattern(text, runtime_father_rsi_patched, runtime_mask, sizeof(runtime_father_rsi_patched));
	plan->pregnancy_a = FindPattern(text, pregnancy_father_a, pregnancy_father_a_mask, sizeof(pregnancy_father_a));
	plan->pregnancy_b = FindPattern(text, pregnancy_father_b, pregnancy_father_b_mask, sizeof(pregnancy_father_b));
	plan->pregnancy_a_patched = FindPattern(text, pregnancy_father_a_patched, pregnancy_father_a_patched_mask, sizeof(pregnancy_father_a_patched));
	plan->pregnancy_b_patched = FindPattern(text, pregnancy_father_b_patched, pregnancy_father_b_patched_mask, sizeof(pregnancy_father_b_patched));
	plan->real_father_validation = FindPattern(text, real_father_validation, real_father_validation_mask, sizeof(real_father_validation));
	plan->real_father_write = FindPattern(text, real_father_write, real_father_write_mask, sizeof(real_father_write));

	if (plan->runtime_rdi.size() + plan->runtime_rdi_patched.size() != 1 ||
		plan->runtime_rsi.size() + plan->runtime_rsi_patched.size() != 1 ||
		plan->pregnancy_a.size() + plan->pregnancy_a_patched.size() != 1 ||
		plan->pregnancy_b.size() + plan->pregnancy_b_patched.size() != 1 ||
		plan->real_father_validation.size() != 1 ||
		plan->real_father_write.size() != 1) {
		Log("AGP Female Father: signature mismatch; no changes made.");
		return false;
	}
	return true;
}

bool ApplyFemaleFatherPatch(const FemaleFatherPatchPlan& plan) {
	const std::uint8_t unconditional_jump = 0xEB;
	const bool runtime_rdi_ok = plan.runtime_rdi.empty() || WriteBytes(plan.runtime_rdi[0] + 7, &unconditional_jump, 1);
	const bool runtime_rsi_ok = plan.runtime_rsi.empty() || WriteBytes(plan.runtime_rsi[0] + 7, &unconditional_jump, 1);
	const bool pregnancy_a_ok = plan.pregnancy_a.empty() || PatchNearConditionalToUnconditional(plan.pregnancy_a[0] + 8);
	const bool pregnancy_b_ok = plan.pregnancy_b.empty() || PatchNearConditionalToUnconditional(plan.pregnancy_b[0] + 7);
	const std::uint8_t nops[6] = { 0x90, 0x90, 0x90, 0x90, 0x90, 0x90 };
	const bool real_father_validation_ok = WriteBytes(plan.real_father_validation[0] + 7, nops, sizeof(nops));
	const bool persistence_ok = HookFemaleFatherPersistence(plan.real_father_write[0]);
	if (!runtime_rdi_ok || !runtime_rsi_ok || !pregnancy_a_ok || !pregnancy_b_ok || !real_father_validation_ok || !persistence_ok) {
		Log("AGP Female Father: patch write failed; CK3 may be unchanged or partially patched.");
		return false;
	}
	return true;
}

} // namespace agp
