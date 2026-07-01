import unittest

from controllers.voice_model_controller import VoiceModelController


_F5_FIXTURE = [
    {
        "id": "high",
        "gpu_vendor": ["NVIDIA", "AMD", "INTEL", "CPU"],
        "settings": [],
    },
    {
        "id": "high+low",
        "gpu_vendor": ["NVIDIA", "AMD", "INTEL", "CPU"],
        "settings": [
            {
                "key": "f5rvc_f5_device",
                "type": "combobox",
                "options": {
                    "values_nvidia": ["cuda", "cpu"],
                    "default_nvidia": "cuda",
                    "values_amd": ["cpu"],
                    "default_amd": "cpu",
                    "values_intel": ["cpu"],
                    "default_intel": "cpu",
                    "values_other": ["cpu"],
                    "default_other": "cpu",
                },
            },
            {
                "key": "f5rvc_rvc_device",
                "type": "combobox",
                "options": {
                    "values_nvidia": ["dml", "cuda:0", "cpu"],
                    "default_nvidia": "cuda:0",
                    "values_amd": ["dml", "cpu"],
                    "default_amd": "dml",
                    "values_intel": ["dml", "cpu"],
                    "default_intel": "dml",
                    "values_other": ["cpu", "dml"],
                    "default_other": "cpu",
                },
            },
            {
                "key": "f5rvc_is_half",
                "type": "combobox",
                "options": {"values": ["True", "False"], "default": "True"},
            },
        ],
    },
]


class VoiceModelControllerTests(unittest.TestCase):
    def _make_controller_stub(self) -> VoiceModelController:
        controller = VoiceModelController.__new__(VoiceModelController)
        controller.gpu_name = "Intel Arc"
        return controller

    def test_f5_high_low_defaults_are_adapted_for_intel(self):
        controller = self._make_controller_stub()

        adapted = controller.finalize_model_settings(_F5_FIXTURE, "INTEL", [])

        model = next(item for item in adapted if item["id"] == "high+low")
        settings = {item["key"]: item for item in model["settings"]}

        self.assertTrue(model["compat_supported"])
        self.assertTrue(model["compat_warning"])

        self.assertEqual(settings["f5rvc_f5_device"]["options"]["values"], ["cpu"])
        self.assertEqual(settings["f5rvc_f5_device"]["options"]["default"], "cpu")
        self.assertTrue(settings["f5rvc_f5_device"]["locked"])

        self.assertEqual(settings["f5rvc_rvc_device"]["options"]["values"], ["dml", "cpu"])
        self.assertEqual(settings["f5rvc_rvc_device"]["options"]["default"], "dml")

        self.assertEqual(settings["f5rvc_is_half"]["options"]["default"], "False")
        self.assertTrue(settings["f5rvc_is_half"]["locked"])

    def test_f5_high_is_marked_supported_on_intel(self):
        controller = self._make_controller_stub()

        adapted = controller.finalize_model_settings(_F5_FIXTURE, "INTEL", [])

        model = next(item for item in adapted if item["id"] == "high")
        self.assertTrue(model["compat_supported"])
        self.assertIn("INTEL", model["gpu_vendor"])
        self.assertTrue(model["compat_warning"])


if __name__ == "__main__":
    unittest.main()
