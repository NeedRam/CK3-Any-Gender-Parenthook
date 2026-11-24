#pragma once
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <vector>
namespace agp {
struct StubCode {
    std::vector<std::uint8_t> bytes;
    void Emit(std::initializer_list<std::uint8_t> part) { bytes.insert(bytes.end(), part); }
    template <typename T> void Value(T value) {
        const auto* begin = reinterpret_cast<const std::uint8_t*>(&value);
        bytes.insert(bytes.end(), begin, begin + sizeof(T));
    }
    void AbsoluteCall(const void* function) {
        Emit({0x48, 0xB8}); Value(reinterpret_cast<std::uintptr_t>(function)); Emit({0xFF, 0xD0});
    }
    void Branch8(std::size_t immediate, std::size_t target) {
        bytes.at(immediate) = static_cast<std::uint8_t>(static_cast<std::int8_t>(target - immediate - 1));
    }
};
}
