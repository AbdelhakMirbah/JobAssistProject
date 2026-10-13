import dotenv from 'dotenv';
dotenv.config();

const OLLAMA_HOST = process.env.OLLAMA_HOST || 'http://localhost:11434';
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || 'mistral';

async function testOllama() {
  console.log(`🦙 Testing local Ollama service at ${OLLAMA_HOST} with model "${OLLAMA_MODEL}"...`);
  try {
    const res = await fetch(`${OLLAMA_HOST}/api/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: OLLAMA_MODEL,
        prompt: 'Return a valid JSON object with {"status": "ok", "provider": "ollama", "message": "Ollama is ready and operational for job tailoring."}',
        format: 'json',
        stream: false
      })
    });

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${await res.text()}`);
    }

    const data = await res.json();
    const parsed = JSON.parse(data.response);
    console.log('✅ Local Ollama is operational!');
    console.log('🤖 Response:', parsed);
  } catch (err) {
    console.error('❌ Ollama test failed:', err.message);
    console.error('💡 Make sure Ollama is running (`brew services start ollama` or `ollama serve`).');
    process.exit(1);
  }
}

testOllama();
