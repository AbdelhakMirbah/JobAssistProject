import dotenv from 'dotenv';
import fs from 'fs';
import path from 'path';

dotenv.config();

const token = process.env.TELEGRAM_BOT_TOKEN;
if (!token) {
  console.error('❌ TELEGRAM_BOT_TOKEN is missing in .env');
  process.exit(1);
}

async function checkChatId() {
  console.log('🔄 Checking Telegram messages for @Mirbahbot...');
  try {
    const res = await fetch(`https://api.telegram.org/bot${token}/getUpdates`);
    const data = await res.json();

    if (!data.ok) {
      throw new Error(data.description || 'Failed to fetch updates');
    }

    const updates = data.result || [];
    if (updates.length === 0) {
      console.log('⏳ No messages received yet.');
      console.log('👉 Please open Telegram, go to: https://t.me/Mirbahbot and click START (or send "hello").');
      console.log('Then run this script again: npm run get-chat-id');
      return;
    }

    // Get the latest message
    const lastUpdate = updates[updates.length - 1];
    const message = lastUpdate.message || lastUpdate.channel_post || lastUpdate.callback_query?.message;
    const chat = message?.chat;

    if (!chat || !chat.id) {
      console.log('⚠️ Could not find chat ID in update payload.');
      return;
    }

    const chatId = chat.id.toString();
    const username = chat.username ? `@${chat.username}` : (chat.first_name || 'User');
    console.log(`✅ FOUND CHAT ID: ${chatId} (${username})`);

    // Update .env file automatically
    const envPath = path.resolve(process.cwd(), '.env');
    if (fs.existsSync(envPath)) {
      let envContent = fs.readFileSync(envPath, 'utf8');
      if (envContent.includes('TELEGRAM_CHAT_ID=')) {
        envContent = envContent.replace(/TELEGRAM_CHAT_ID=.*/g, `TELEGRAM_CHAT_ID=${chatId}`);
      } else {
        envContent += `\nTELEGRAM_CHAT_ID=${chatId}\n`;
      }
      fs.writeFileSync(envPath, envContent, 'utf8');
      console.log(`💾 Successfully saved TELEGRAM_CHAT_ID=${chatId} to .env!`);
    }

    // Send confirmation message to the bot
    await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: chatId,
        text: '🎉 Félicitations Abdelhak ! Votre bot Mirbahbot est connecté avec succès à votre assistant local n8n.'
      })
    });
    console.log('📱 Confirmation message sent to your Telegram!');
  } catch (err) {
    console.error('❌ Error checking Telegram updates:', err.message);
  }
}

checkChatId();
