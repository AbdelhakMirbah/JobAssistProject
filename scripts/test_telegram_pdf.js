import dotenv from 'dotenv';
import fs from 'fs';
import path from 'path';

dotenv.config();

const token = process.env.TELEGRAM_BOT_TOKEN;
const chatId = process.env.TELEGRAM_CHAT_ID;

if (!token || !chatId) {
  console.error('❌ Missing token or chatId in .env');
  process.exit(1);
}

async function testSendPdf() {
  console.log(`📤 Sending test notification & CV to Telegram (chat_id: ${chatId})...`);

  // 1. Send text message with inline buttons
  const textMsg = `🎯 *Test Notification - Job Assistant n8n*\n\n🏢 *Company:* Doctolib\n💼 *Role:* Senior Data & Software Engineer\n📊 *Fit Score:* *92%* ⭐\n\n✅ *Matched Keywords:* Python, SQL, Kafka, Data Warehouse, Spring Boot\n\n👇 *Vos documents personnalisés sont joints ci-dessous :*`;

  const inlineKeyboard = {
    inline_keyboard: [
      [
        { text: '✅ Postuler / Marquer Postulé', callback_data: 'APPLY:test_123' },
        { text: '❌ Ignorer / Archiver', callback_data: 'SKIP:test_123' }
      ]
    ]
  };

  const textRes = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: chatId,
      text: textMsg,
      parse_mode: 'Markdown',
      reply_markup: inlineKeyboard
    })
  });

  const textData = await textRes.json();
  if (!textData.ok) {
    console.error('❌ Error sending message:', textData);
    return;
  }
  console.log('✅ Telegram card with buttons sent!');

  // 2. Send CV PDF
  const cvPath = path.resolve(process.cwd(), 'output/preview_cv.pdf');
  if (fs.existsSync(cvPath)) {
    const fileBuffer = fs.readFileSync(cvPath);
    const formData = new FormData();
    formData.append('chat_id', chatId);
    formData.append('caption', '📄 Abdelhak Mirbah - CV Adapté (Doctolib)');
    formData.append('document', new Blob([fileBuffer], { type: 'application/pdf' }), 'Abdelhak_Mirbah_CV_Doctolib.pdf');

    const docRes = await fetch(`https://api.telegram.org/bot${token}/sendDocument`, {
      method: 'POST',
      body: formData
    });
    const docData = await docRes.json();
    if (docData.ok) {
      console.log('✅ Tailored CV PDF sent to Telegram!');
    }
  }

  // 3. Send Cover Letter PDF
  const letterPath = path.resolve(process.cwd(), 'output/preview_cover_letter.pdf');
  if (fs.existsSync(letterPath)) {
    const fileBuffer = fs.readFileSync(letterPath);
    const formData = new FormData();
    formData.append('chat_id', chatId);
    formData.append('caption', '✉️ Abdelhak Mirbah - Lettre de Motivation (Doctolib)');
    formData.append('document', new Blob([fileBuffer], { type: 'application/pdf' }), 'Abdelhak_Mirbah_Lettre_Doctolib.pdf');

    const docRes = await fetch(`https://api.telegram.org/bot${token}/sendDocument`, {
      method: 'POST',
      body: formData
    });
    const docData = await docRes.json();
    if (docData.ok) {
      console.log('✅ Tailored Cover Letter PDF sent to Telegram!');
    }
  }

  console.log('🎉 Test transmission complete! Check your Telegram app.');
}

testSendPdf();
