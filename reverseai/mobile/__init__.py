"""Mobile app analysis — Android APKs (and room for iOS IPAs).

An APK is a ZIP: this inspects its structure, analyzes bundled native libraries
as ELF binaries (arch/imports), counts DEX bytecode, and recovers the package
name and requested permissions from the (binary) AndroidManifest. Full decompile
+ modify + resign needs external tooling (apktool/jadx/apksigner); this is the
analysis + RE foundation.
"""

from .apk import APKReport, analyze_apk, is_apk

__all__ = ["analyze_apk", "is_apk", "APKReport"]
