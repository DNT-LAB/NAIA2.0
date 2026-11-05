"""NAIA - Anima Ref Adapter v2 + Spectrum: keep the no-reference pass on its own forecaster.

Installed by NAIA into the managed ComfyUI as ``custom_nodes/naia-ref-spectrum-key/__init__.py``
(core/anima_engine/ref_adapter.py). Do not edit the installed copy - NAIA replaces it by hash.

Spectrum keys its feature forecasters by ``cond_or_uncond`` (the index of a cond in the list handed to
``calc_cond_batch``). Anima Ref Adapter v2's ``ref_guidance`` runs one extra pass without the reference
(``transformer_options["anima_ref_off"]``) through ``calc_cond_batch(model, [uncond])`` - index 0, the
same key as the real cond branch. Under Spectrum the two then share one forecaster and the image turns
to noise (measured 2026-11-05: MAE 94 against the unaccelerated image; with this node 14).

This MODEL patch moves that pass to index 2 (``[None, None, uncond]``). ComfyUI skips ``None`` conds, so
the computation is unchanged (bit-identical without Spectrum, and with ref_guidance 1); only the
forecaster key differs. Place it after the Anima Ref Adapter node, before the sampler.
"""
import comfy.patcher_extension

NO_REF_KEY = "anima_ref_off"   # ComfyUI-Anima-Ref-Adapter 0.2.0 NO_REF_KEY
NO_REF_SLOT = 2                 # 0 = cond, 1 = uncond, 2 = uncond without the reference
WRAPPER_KEY = "naia_ref_spectrum_key"


def _calc_cond_batch_wrapper(executor, model, conds, x_in, timestep, model_options):
    options = model_options.get("transformer_options", {}) if isinstance(model_options, dict) else {}
    if options.get(NO_REF_KEY) and len(conds) == 1:
        out = executor(model, [None] * NO_REF_SLOT + list(conds), x_in, timestep, model_options)
        return [out[NO_REF_SLOT]]
    return executor(model, conds, x_in, timestep, model_options)


class NaiaRefSpectrumKey:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",)}}

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "apply"
    CATEGORY = "NAIA"

    def apply(self, model):
        patched = model.clone()
        patched.add_wrapper_with_key(comfy.patcher_extension.WrappersMP.CALC_COND_BATCH, WRAPPER_KEY,
                                     _calc_cond_batch_wrapper)
        return (patched,)


NODE_CLASS_MAPPINGS = {"NaiaRefSpectrumKey": NaiaRefSpectrumKey}
NODE_DISPLAY_NAME_MAPPINGS = {"NaiaRefSpectrumKey": "NAIA Ref + Spectrum key split"}
