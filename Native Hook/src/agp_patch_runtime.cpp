#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "agp_patch_runtime.h"

#include <cstdio>
#include <cstring>
#include <algorithm>

namespace agp {
namespace {
struct PendingWrite {
    std::uint8_t* address;
    std::vector<std::uint8_t> before, after;
};
bool staging = false;
std::vector<PendingWrite> pending;
std::vector<void*> allocations;

bool WriteDirect(std::uint8_t* address, const std::uint8_t* bytes, std::size_t count) {
    DWORD old_protection = 0;
    if (!VirtualProtect(address, count, PAGE_EXECUTE_READWRITE, &old_protection)) return false;
    std::memcpy(address, bytes, count);
    const bool copied = !std::memcmp(address, bytes, count);
    const bool flushed = FlushInstructionCache(GetCurrentProcess(), address, count) != FALSE;
    DWORD ignored = 0;
    const bool restored = VirtualProtect(address, count, old_protection, &ignored) != FALSE;
    return copied && flushed && restored;
}
}

void BeginPatchTransaction() {
    AbortPatchTransaction();
    staging = true;
}
void AbortPatchTransaction() {
    staging = false;
    pending.clear();
    for (auto* allocation : allocations) VirtualFree(allocation, 0, MEM_RELEASE);
    allocations.clear();
}
bool CommitPatchTransaction(std::size_t fault_after) {
    if (!staging) return false;
    staging = false;
    std::size_t attempted = 0;
    bool ok = true;
    for (const auto& write : pending) {
        if (attempted == fault_after) { ok = false; break; }
        ++attempted;
        if (!WriteDirect(write.address, write.after.data(), write.after.size())) { ok = false; break; }
    }
    if (!ok) {
        bool restored = true;
        while (attempted) {
            const auto& write = pending[--attempted];
            restored = WriteDirect(write.address, write.before.data(), write.before.size()) && restored;
        }
        Log(restored ? "AGP: patch transaction rolled back and verified. Exit without saving." :
            "AGP: PATCH ROLLBACK FAILED. Exit CK3 immediately without saving.");
        // A thread might have entered a relay before rollback; keep allocations
        // resident until process exit even when the original bytes were restored.
        allocations.clear();
        pending.clear();
        return false;
    }
    allocations.clear();
    pending.clear();
    return true;
}

bool StageDetour(std::uint8_t* site, std::uint8_t* target, std::size_t overwrite) {
    if (overwrite < 5 || !IsRel32Reachable(site + 5, target)) return false;
    std::vector<std::uint8_t> bytes(overwrite, 0x90);
    bytes[0] = 0xE9;
    const auto delta = static_cast<std::int32_t>(target - (site + 5));
    std::memcpy(bytes.data() + 1, &delta, sizeof(delta));
    return WriteBytes(site, bytes.data(), bytes.size());
}

void Log(const char* message) {
	char module_path[MAX_PATH]{};
	if (GetModuleFileNameA(nullptr, module_path, MAX_PATH) == 0) {
		return;
	}
	char* separator = std::strrchr(module_path, '\\');
	if (separator == nullptr) {
		return;
	}
	std::strcpy(separator + 1, "agp_parenthook.log");
	HANDLE file = CreateFileA(module_path, FILE_APPEND_DATA, FILE_SHARE_READ, nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
	if (file == INVALID_HANDLE_VALUE) {
		return;
	}
	DWORD written = 0;
	WriteFile(file, message, static_cast<DWORD>(std::strlen(message)), &written, nullptr);
	WriteFile(file, "\r\n", 2, &written, nullptr);
	CloseHandle(file);
}

bool WriteBytes(std::uint8_t* address, const std::uint8_t* bytes, std::size_t count) {
    if (staging) {
        pending.push_back({address, {address, address + count}, {bytes, bytes + count}});
        return true;
    }
    return WriteDirect(address, bytes, count);
}

bool GetTextSection(TextSection* result) {
	auto* base = reinterpret_cast<std::uint8_t*>(GetModuleHandleW(nullptr));
	if (base == nullptr) {
		return false;
	}
	auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
	if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
		return false;
	}
	auto* nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
	if (nt->Signature != IMAGE_NT_SIGNATURE || nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC) {
		return false;
	}
	auto* section = IMAGE_FIRST_SECTION(nt);
	for (WORD index = 0; index < nt->FileHeader.NumberOfSections; ++index, ++section) {
		if (std::memcmp(section->Name, ".text", 5) == 0) {
			result->begin = base + section->VirtualAddress;
			result->size = section->Misc.VirtualSize;
			return true;
		}
	}
	return false;
}

std::vector<std::uint8_t*> FindPattern(const TextSection& section, const std::uint8_t* pattern, const char* mask, std::size_t length) {
	std::vector<std::uint8_t*> matches;
	if (length > section.size) {
		return matches;
	}
	for (std::size_t offset = 0; offset <= section.size - length; ++offset) {
		bool match = true;
		for (std::size_t byte = 0; byte < length; ++byte) {
			if (mask[byte] == 'x' && section.begin[offset + byte] != pattern[byte]) {
				match = false;
				break;
			}
		}
		if (match) {
			matches.push_back(section.begin + offset);
		}
	}
	return matches;
}

bool IsRel32Reachable(const void* source_after_immediate, const void* target) {
	const auto delta = reinterpret_cast<const std::uint8_t*>(target) - reinterpret_cast<const std::uint8_t*>(source_after_immediate);
	return delta >= INT32_MIN && delta <= INT32_MAX;
}

void WriteRel32(std::uint8_t* immediate, const void* target) {
	const auto delta = reinterpret_cast<const std::uint8_t*>(target) - (immediate + 4);
	const auto value = static_cast<std::int32_t>(delta);
    WriteBytes(immediate, reinterpret_cast<const std::uint8_t*>(&value), sizeof(value));
}

std::uint8_t* AllocateNear(const void* target, std::size_t size) {
	SYSTEM_INFO info{};
	GetSystemInfo(&info);
	const auto granularity = static_cast<std::uintptr_t>(info.dwAllocationGranularity);
	const auto center = reinterpret_cast<std::uintptr_t>(target);
	const auto minimum = center > 0x7fff0000ULL ? center - 0x7fff0000ULL : 0;
	const auto maximum = center + 0x7fff0000ULL;

	for (std::uintptr_t address = center; address < maximum;) {
		MEMORY_BASIC_INFORMATION region{};
		if (VirtualQuery(reinterpret_cast<const void*>(address), &region, sizeof(region)) == 0) {
			break;
		}
		const auto region_start = reinterpret_cast<std::uintptr_t>(region.BaseAddress);
		const auto region_end = region_start + region.RegionSize;
		if (region.State == MEM_FREE) {
			auto candidate = (region_start + granularity - 1) & ~(granularity - 1);
			if (candidate >= minimum && candidate < maximum && region_end >= candidate + size) {
				if (auto* allocation = static_cast<std::uint8_t*>(VirtualAlloc(reinterpret_cast<void*>(candidate), size, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE))) {
					if (IsRel32Reachable(allocation, target)) {
                        if (staging) allocations.push_back(allocation);
						return allocation;
					}
					VirtualFree(allocation, 0, MEM_RELEASE);
				}
			}
		}
		if (region_end <= address) {
			break;
		}
		address = region_end;
	}
	return nullptr;
}

bool PatchNearConditionalToUnconditional(std::uint8_t* conditional_jump) {
	const auto original_displacement = *reinterpret_cast<std::int32_t*>(conditional_jump + 2);
	auto* const target = conditional_jump + 6 + original_displacement;
	if (!IsRel32Reachable(conditional_jump + 5, target)) {
		return false;
	}
	std::uint8_t unconditional_jump[6] = { 0xE9, 0x00, 0x00, 0x00, 0x00, 0x90 };
	const auto displacement = static_cast<std::int32_t>(target - (conditional_jump + 5));
	std::memcpy(unconditional_jump + 1, &displacement, sizeof(displacement));
	return WriteBytes(conditional_jump, unconditional_jump, sizeof(unconditional_jump));
}

} // namespace agp
