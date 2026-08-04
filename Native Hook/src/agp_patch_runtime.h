#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace agp {

struct TextSection {
	std::uint8_t* begin;
	std::size_t size;
};

void Log(const char* message);
bool WriteBytes(std::uint8_t* address, const std::uint8_t* bytes, std::size_t count);
bool GetTextSection(TextSection* result);
std::vector<std::uint8_t*> FindPattern(const TextSection& section, const std::uint8_t* pattern, const char* mask, std::size_t length);
bool IsRel32Reachable(const void* source_after_immediate, const void* target);
void WriteRel32(std::uint8_t* immediate, const void* target);
std::uint8_t* AllocateNear(const void* target, std::size_t size);
bool PatchNearConditionalToUnconditional(std::uint8_t* conditional_jump);

} // namespace agp
