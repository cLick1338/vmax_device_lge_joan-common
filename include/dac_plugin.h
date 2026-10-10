/*
 * Copyright (C) 2024 The LineageOS Project
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

/*
 * Board specific devices and paths
 *
 * If your device exposes these controls in another place, you can either
 * symlink to the locations given here, or override this header in your
 * device tree.
 */

#define DEFAULT_BACKEND "headphones"
#define DEFAULT_INTERFACE "SLIMBUS_6_RX"
#define ESS_BYPASS_MODE_MIXER_PATH "ess-bypass-mode"

#define HIFI_DAC_BACKEND "QUAT_MI2S_RX"
#define HIFI_DAC_INTERFACE "QUAT_MI2S_RX"
#define ESS_HIFI_MODE_MIXER_PATH "ess-hifi-mode"

// DAC link format controls; the HAL only programs known backends, not HIFI_DAC_BACKEND
#define HIFI_DAC_SAMPLE_RATE_CTL "QUAT_MI2S_RX SampleRate"
#define HIFI_DAC_FORMAT_CTL "QUAT_MI2S_RX Format"
