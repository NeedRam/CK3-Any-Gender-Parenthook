#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "agp_male_mother.h"

#include <cstring>

namespace agp {
namespace {

bool HookMaleMotherPersistence(std::uint8_t* site) {
	// The ordinary mother save field is already written by CK3 at [rdx]. Add
	// the explicit-mother marker at [rdx+0Ch] when that parent is male, so the
	// load-time reciprocal-child pass can restore the native mother role rather
	// than inferring father from sex.
	auto* const resume = site + 0x0c;
	auto* const stub = AllocateNear(site, 32);
	if (stub == nullptr || !IsRel32Reachable(stub + 29, resume)) {
		return false;
	}

	const std::uint8_t code[] = {
		0x8B, 0x46, 0x18,
		0x89, 0x02,
		0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x00,
		0x75, 0x03,
		0x89, 0x42, 0x0C,
		0x48, 0x8B, 0x87, 0xB8, 0x01, 0x00, 0x00,
		0xE9, 0x00, 0x00, 0x00, 0x00
	};
	if (!WriteBytes(stub, code, sizeof(code))) {
		return false;
	}
	WriteRel32(stub + 25, resume);
	FlushInstructionCache(GetCurrentProcess(), stub, sizeof(code));

	std::uint8_t jump[5] = { 0xE9, 0x00, 0x00, 0x00, 0x00 };
	const auto jump_displacement = static_cast<std::int32_t>(stub - (site + 5));
	std::memcpy(jump + 1, &jump_displacement, sizeof(jump_displacement));
	return WriteBytes(site, jump, sizeof(jump));
}

const std::uint8_t runtime_mother_rdi[] = { 0x80, 0xBF, 0x99, 0x01, 0x00, 0x00, 0x01, 0x74, 0x00, 0x4C, 0x8D, 0x05, 0x00, 0x00, 0x00, 0x00, 0xC7, 0x85, 0x30, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xBA, 0x00, 0x02, 0x00, 0x00 };
const std::uint8_t runtime_mother_rsi[] = { 0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x01, 0x74, 0x00, 0x4C, 0x8D, 0x05, 0x00, 0x00, 0x00, 0x00, 0xC7, 0x85, 0x30, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xBA, 0x00, 0x02, 0x00, 0x00 };
const std::uint8_t runtime_mother_rdi_patched[] = { 0x80, 0xBF, 0x99, 0x01, 0x00, 0x00, 0x01, 0xEB, 0x00, 0x4C, 0x8D, 0x05, 0x00, 0x00, 0x00, 0x00, 0xC7, 0x85, 0x30, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xBA, 0x00, 0x02, 0x00, 0x00 };
const std::uint8_t runtime_mother_rsi_patched[] = { 0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x01, 0xEB, 0x00, 0x4C, 0x8D, 0x05, 0x00, 0x00, 0x00, 0x00, 0xC7, 0x85, 0x30, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xBA, 0x00, 0x02, 0x00, 0x00 };
const char runtime_mask[] = "xxxxxxxx?xxx????xxxxxxxxxxxxxxx";

const std::uint8_t pregnancy_mother[] = { 0x80, 0xBB, 0x99, 0x01, 0x00, 0x00, 0x00, 0x0F, 0x85, 0x00, 0x00, 0x00, 0x00, 0x48, 0x8D, 0x54, 0x24, 0x40, 0x48, 0x8B, 0xCB, 0xE8 };
const char pregnancy_mother_mask[] = "xxxxxxxxx????xxxxxxxxx";
const std::uint8_t pregnancy_mother_patched[] = { 0x80, 0xBB, 0x99, 0x01, 0x00, 0x00, 0x00, 0xE9, 0x00, 0x00, 0x00, 0x00, 0x90, 0x48, 0x8D, 0x54, 0x24, 0x40, 0x48, 0x8B, 0xCB, 0xE8 };
const char pregnancy_mother_patched_mask[] = "xxxxxxxx?????xxxxxxxxx";

const std::uint8_t real_mother_validation[] = { 0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x00, 0x0F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x48, 0x3B, 0xF3, 0x0F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x48, 0x8B, 0x05 };
const char real_mother_validation_mask[] = "xxxxxxxxx????xxxxx????xxx";
const std::uint8_t real_mother_validation_patched[] = { 0x80, 0xBE, 0x99, 0x01, 0x00, 0x00, 0x01, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x48, 0x3B, 0xF3, 0x0F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x48, 0x8B, 0x05 };
const char real_mother_validation_patched_mask[] = "xxxxxxxxxxxxxxxxxx????xxx";
const std::uint8_t real_mother_write[] = { 0x8B, 0x46, 0x18, 0x89, 0x02, 0x48, 0x8B, 0x87, 0xB8, 0x01, 0x00, 0x00 };
const char real_mother_write_mask[] = "xxxxxxxxxxxx";

} // namespace

bool PrepareMaleMotherPatch(const TextSection& text, MaleMotherPatchPlan* plan) {
	plan->runtime_rdi = FindPattern(text, runtime_mother_rdi, runtime_mask, sizeof(runtime_mother_rdi));
	plan->runtime_rsi = FindPattern(text, runtime_mother_rsi, runtime_mask, sizeof(runtime_mother_rsi));
	plan->runtime_rdi_patched = FindPattern(text, runtime_mother_rdi_patched, runtime_mask, sizeof(runtime_mother_rdi_patched));
	plan->runtime_rsi_patched = FindPattern(text, runtime_mother_rsi_patched, runtime_mask, sizeof(runtime_mother_rsi_patched));
	plan->pregnancy = FindPattern(text, pregnancy_mother, pregnancy_mother_mask, sizeof(pregnancy_mother));
	plan->pregnancy_patched = FindPattern(text, pregnancy_mother_patched, pregnancy_mother_patched_mask, sizeof(pregnancy_mother_patched));
	plan->real_mother_validation = FindPattern(text, real_mother_validation, real_mother_validation_mask, sizeof(real_mother_validation));
	plan->real_mother_validation_patched = FindPattern(text, real_mother_validation_patched, real_mother_validation_patched_mask, sizeof(real_mother_validation_patched));
	plan->real_mother_write = FindPattern(text, real_mother_write, real_mother_write_mask, sizeof(real_mother_write));

	if (plan->runtime_rdi.size() + plan->runtime_rdi_patched.size() != 1 ||
		plan->runtime_rsi.size() + plan->runtime_rsi_patched.size() != 1 ||
		plan->pregnancy.size() + plan->pregnancy_patched.size() != 2 ||
		plan->real_mother_validation.size() + plan->real_mother_validation_patched.size() != 1 ||
		plan->real_mother_write.size() != 1) {
		Log("AGP Male Mother: signature mismatch; no changes made.");
		return false;
	}
	return true;
}

bool ApplyMaleMotherPatch(const MaleMotherPatchPlan& plan) {
	const std::uint8_t unconditional_jump = 0xEB;
	const bool runtime_rdi_ok = plan.runtime_rdi.empty() || WriteBytes(plan.runtime_rdi[0] + 7, &unconditional_jump, 1);
	const bool runtime_rsi_ok = plan.runtime_rsi.empty() || WriteBytes(plan.runtime_rsi[0] + 7, &unconditional_jump, 1);
	bool pregnancy_ok = true;
	for (auto* match : plan.pregnancy) {
		pregnancy_ok = PatchNearConditionalToUnconditional(match + 7) && pregnancy_ok;
	}
	const std::uint8_t nops[6] = { 0x90, 0x90, 0x90, 0x90, 0x90, 0x90 };
	const bool real_mother_validation_ok = plan.real_mother_validation.empty() || WriteBytes(plan.real_mother_validation[0] + 7, nops, sizeof(nops));
	const bool persistence_ok = HookMaleMotherPersistence(plan.real_mother_write[0]);
	if (!runtime_rdi_ok || !runtime_rsi_ok || !pregnancy_ok || !real_mother_validation_ok || !persistence_ok) {
		Log("AGP Male Mother: patch write failed; CK3 may be unchanged or partially patched.");
		return false;
	}
	return true;
}

} // namespace agp
