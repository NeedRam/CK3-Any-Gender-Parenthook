#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdio>
#include <cstring>
#include <cwchar>
#include <string>

namespace {

HMODULE g_loader_module = nullptr;
INIT_ONCE g_dxcompiler_init = INIT_ONCE_STATIC_INIT;

using DxcCreateInstance_t = HRESULT(WINAPI*)(REFCLSID, REFIID, LPVOID*);
using DxcCreateInstance2_t = HRESULT(WINAPI*)(void*, REFCLSID, REFIID, LPVOID*);

DxcCreateInstance_t g_DxcCreateInstance = nullptr;
DxcCreateInstance2_t g_DxcCreateInstance2 = nullptr;

void Log(const char* message) {
	char path[MAX_PATH]{};
	if (GetModuleFileNameA(g_loader_module, path, MAX_PATH) == 0) return;
	char* separator = std::strrchr(path, '\\');
	if (separator == nullptr) return;
	std::strcpy(separator + 1, "agp_dxcompiler_loader.log");
	HANDLE file = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ, nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
	if (file == INVALID_HANDLE_VALUE) return;
	DWORD written = 0;
	WriteFile(file, message, static_cast<DWORD>(std::strlen(message)), &written, nullptr);
	WriteFile(file, "\r\n", 2, &written, nullptr);
	CloseHandle(file);
}

BOOL CALLBACK InitializeRealDxcompiler(PINIT_ONCE, PVOID, PVOID*) {
	wchar_t path[MAX_PATH]{};
	if (GetModuleFileNameW(g_loader_module, path, MAX_PATH) == 0) return FALSE;
	wchar_t* separator = std::wcsrchr(path, L'\\');
	if (separator == nullptr) return FALSE;
	std::wcscpy(separator + 1, L"dxcompiler_original.dll");
	HMODULE original = LoadLibraryW(path);
	if (original == nullptr) {
		Log("AGP DXCompiler Loader: original dxcompiler_original.dll failed to load.");
		return FALSE;
	}
	g_DxcCreateInstance = reinterpret_cast<DxcCreateInstance_t>(GetProcAddress(original, "DxcCreateInstance"));
	g_DxcCreateInstance2 = reinterpret_cast<DxcCreateInstance2_t>(GetProcAddress(original, "DxcCreateInstance2"));
	if (g_DxcCreateInstance == nullptr || g_DxcCreateInstance2 == nullptr) {
		Log("AGP DXCompiler Loader: original exports were incomplete.");
		return FALSE;
	}
	return TRUE;
}

bool EnsureRealDxcompiler() {
	return InitOnceExecuteOnce(&g_dxcompiler_init, InitializeRealDxcompiler, nullptr, nullptr) != FALSE;
}

DWORD WINAPI LoadPayloadThread(LPVOID) {
	wchar_t path[MAX_PATH]{};
	if (GetModuleFileNameW(g_loader_module, path, MAX_PATH) == 0) return 1;
	wchar_t* separator = std::wcsrchr(path, L'\\');
	if (separator == nullptr) return 1;
	std::wcscpy(separator + 1, L"AGP Native Hook\\agp_parenthook.dll");
	if (LoadLibraryW(path) == nullptr) {
		Log("AGP DXCompiler Loader: payload failed to load.");
		return 1;
	}
	Log("AGP DXCompiler Loader: payload loaded.");
	return 0;
}

} // namespace

extern "C" __declspec(dllexport) HRESULT WINAPI DxcCreateInstance(REFCLSID class_id, REFIID interface_id, LPVOID* result) {
	if (!EnsureRealDxcompiler() || g_DxcCreateInstance == nullptr) return E_FAIL;
	return g_DxcCreateInstance(class_id, interface_id, result);
}

extern "C" __declspec(dllexport) HRESULT WINAPI DxcCreateInstance2(void* allocator, REFCLSID class_id, REFIID interface_id, LPVOID* result) {
	if (!EnsureRealDxcompiler() || g_DxcCreateInstance2 == nullptr) return E_FAIL;
	return g_DxcCreateInstance2(allocator, class_id, interface_id, result);
}

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
	if (reason == DLL_PROCESS_ATTACH) {
		g_loader_module = module;
		DisableThreadLibraryCalls(module);
		HANDLE thread = CreateThread(nullptr, 0, LoadPayloadThread, nullptr, 0, nullptr);
		if (thread != nullptr) CloseHandle(thread);
	}
	return TRUE;
}
