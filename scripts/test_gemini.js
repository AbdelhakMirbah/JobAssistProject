import dotenv from 'dotenv';
dotenv.config();

const apiKey = process.env.GEMINI_API_KEY;

if (!apiKey || apiKey === 'your_gemini_api_key_here') {
  console.error('❌ GEMINI_API_KEY is not set in .env. Please add your key from https://aistudio.google.com/app/apikey');
  process.exit(1);
}

const modelName = process.env.GEMINI_MODEL || 'gemini-3-flash-preview';

async function testGemini() {
  console.log(`🔄 Testing Google Gemini API with model ${modelName}...`);
  const endpoint = `https://generativelanguage.googleapis.com/v1beta/models/${modelName}:generateContent?key=${apiKey}`;

  const payload = {
    contents: [
      {
        parts: [
          {
            text: 'Respond with a valid JSON object with key "status": "ok" and "message": "Gemini is connected and ready for CV tailoring."'
          }
        ]
      }
    ],
    generationConfig: {
      responseMimeType: "application/json"
    }
  };

  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`HTTP ${res.status}: ${errText}`);
    }

    const data = await res.json();
    const candidateText = data.candidates?.[0]?.content?.parts?.[0]?.text;
    console.log('✅ Google Gemini is operational!');
    console.log('🤖 Response:', candidateText);
  } catch (error) {
    console.error('❌ Gemini API Error:', error.message);
    process.exit(1);
  }
}

testGemini();
