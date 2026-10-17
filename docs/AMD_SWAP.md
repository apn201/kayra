# Swapping to AMD

## A. Language model: AMD token factory (notebooks.amd.com/tokenfactory)

Five minutes. Nothing in the code changes.

1. Sign in to the token factory. Copy the API key and the API base URL shown there. The base URL is not public; it is on that page after sign-in.
2. Open `.env`. Comment out the four OpenRouter lines (`KAYRA_LLM_BACKEND=other` ... `KAYRA_LLM_MODEL_TEXT=...`). Uncomment the six lines under "AMD token factory" and paste the key and the base URL.
3. Check the endpoint and pick the models:

   ```
   python tools/llm_check.py
   ```

   It lists the models, skips speech/vision/document ones, and scores every chat model on Käyrä's own three tasks, graded by code: hypothesis programs (validator), an operator note into a program, and number-grounded prose (guardrails). It prints the recommended `KAYRA_LLM_MODEL_CODE` and `KAYRA_LLM_MODEL_TEXT`. Put those in `.env`. If `/models` 404s, it retries with `/v1` and tells you which base URL to keep. Results go to `artifacts/model_check.json`.

   Default in the block is DeepSeek-V4.1-Flash for both, the same model the OpenRouter stand-in used on 2026-10-17, so the stand-in results stay comparable.

4. Rerun everything that uses the model:

   ```
   python -m kayra.run all        # real data loop, synthetic arm C, model steps (about 45 min on a laptop)
   python tools/build_web.py
   ```

   Short on time: `python -m kayra.run ai` redoes only the explanations, the site-context arm and the write-up (a few minutes). The hypothesis notebook and synthetic arm C then still show the stand-in model, and say so.

The panel status changes from STAND-IN (not AMD) to ONLINE by itself.

## B. Fitter on an AMD GPU (optional, only if a droplet is available)

The fitter is PyTorch and picks the device at runtime. On a ROCm machine:

```
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"   # must end in +rocm, True
python -m kayra.run bench      # fills the GPU row in artifacts/benchmark.json
python -m kayra.run all        # optional: the whole run on the GPU
```

Install anything extra with `pip install --no-deps` and check `torch.__version__` again after. Pull `artifacts/` back, then `python tools/build_web.py`. Destroy the droplet when done; powering off does not stop billing.

## C. If neither comes back

Ship as is. The panel says STAND-IN and NOT MEASURED where those apply, and the write-up says CPU numbers are CPU numbers.
