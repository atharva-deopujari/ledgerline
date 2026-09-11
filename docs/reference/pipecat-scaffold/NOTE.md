# Pipecat reference scaffold (for diffing only)

Generated 2026-09-11 with Pipecat CLI 1.9.0:

    pipecat init ref-bot --bot-type web -t daily -m cascade \
      --stt deepgram_stt --llm openai_llm --tts cartesia_tts --client-framework vanilla

Not our code. Kept so we can diff our hand-written bot.py, Dockerfile and client against
what the framework authors generate for the same stack. Do not import from here.
