const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  downloadMediaMessage,
} = require('@whiskeysockets/baileys')
const express = require('express')
const QRCode = require('qrcode')
const pino = require('pino')
const fs = require('fs')
const path = require('path')

const DATA_DIR = '/data'
const LOG_GROUP = '120363409023550509@g.us'  // history group — all outbound messages mirrored here
const OWNER_PHONE = '918899106088'
const SESSION_DIR = path.join(DATA_DIR, 'session')
const QR_PATH = path.join(DATA_DIR, 'qr.png')
const MESSAGES_FILE = path.join(DATA_DIR, 'messages.jsonl')
const CONTACTS_FILE = path.join(DATA_DIR, 'contacts.json')
const TEXTED_FILE = path.join(DATA_DIR, 'texted.json')  // phones we've initiated contact with

fs.mkdirSync(SESSION_DIR, { recursive: true })

const app = express()
app.use(express.json())

let sock = null
let isConnected = false
let qrAvailable = false
let connectedPhone = null
const recentMessages = []
const MAX_MESSAGES = 200

// contacts: jid → { name, phone }
const contacts = new Map()

// phones we've texted at least once → reply count from them
const textedContacts = new Map()

function loadContacts() {
  if (fs.existsSync(CONTACTS_FILE)) {
    try {
      const saved = JSON.parse(fs.readFileSync(CONTACTS_FILE, 'utf8'))
      for (const [k, v] of Object.entries(saved)) contacts.set(k, v)
      console.log(`[wa] Loaded ${contacts.size} contacts from disk`)
    } catch {}
  }
}

function saveContacts() {
  fs.writeFileSync(CONTACTS_FILE, JSON.stringify(Object.fromEntries(contacts)))
}

function upsertContacts(list) {
  for (const c of list) {
    if (!c.id) continue
    const phone = c.id.split('@')[0]
    const name = c.name || c.notify || c.verifiedName || null
    if (name) contacts.set(c.id, { name, phone })
  }
  saveContacts()
}

function loadTexted() {
  if (fs.existsSync(TEXTED_FILE)) {
    try {
      const saved = JSON.parse(fs.readFileSync(TEXTED_FILE, 'utf8'))
      for (const [k, v] of Object.entries(saved)) textedContacts.set(k, v)
    } catch {}
  }
}

function saveTexted() {
  fs.writeFileSync(TEXTED_FILE, JSON.stringify(Object.fromEntries(textedContacts)))
}

loadContacts()
loadTexted()

function jid(phone) {
  if (phone.includes('@')) return phone
  const digits = phone.replace(/\D/g, '')
  return `${digits}@s.whatsapp.net`
}

function logToGroup(text) {
  if (isConnected) sock.sendMessage(LOG_GROUP, { text }).catch(() => {})
}

const SAVAGE_REPLIES = [
  "Bhai seriously? Still here? 😂 Vineet ka number hai: +91 88991 06088. Please move on.",
  "Okay this is getting clingy 😅 +91 88991 06088 — call him, text him, idk, just not here.",
  "This number is basically a brick wall with WiFi. Try +91 88991 06088.",
  "Error 404: Vineet not found on this number. Last seen at +91 88991 06088 👋",
  "I'm literally a bot with no feelings and even I'm getting tired of this conversation. +91 88991 06088.",
  "Agar is number pe aate raho toh main tumhe block kar dunga. Mazaak nahi. +91 88991 06088 try karo 🙏",
]

async function handleIncoming(msg) {
  const remoteJid = msg.key.remoteJid
  if (!remoteJid || msg.key.fromMe) return
  if (remoteJid === LOG_GROUP) return  // ignore group's own messages
  if (remoteJid.endsWith('@g.us')) return  // ignore other groups
  if (remoteJid === jid(OWNER_PHONE)) return  // ignore owner

  // only reply to contacts we've texted
  if (!textedContacts.has(remoteJid)) return

  const text = msg.message?.conversation || msg.message?.extendedTextMessage?.text || ''
  if (!text) return

  const replyCount = textedContacts.get(remoteJid) || 0
  const contactName = contacts.get(remoteJid)?.name || remoteJid.split('@')[0]
  const phone = remoteJid.split('@')[0]

  // log incoming to group
  logToGroup(`📥 From *${contactName}* (+${phone}):\n${text}`)

  let reply
  if (replyCount === 0) {
    reply = `Hey! This number can't receive messages right now.\nPlease reach Vineet directly at *+91 88991 06088* 🙂`
  } else {
    reply = SAVAGE_REPLIES[Math.min(replyCount - 1, SAVAGE_REPLIES.length - 1)]
  }

  await sock.sendMessage(remoteJid, { text: reply })
  logToGroup(`📤 Auto-reply to *${contactName}* (+${phone}):\n${reply}`)

  textedContacts.set(remoteJid, replyCount + 1)
  saveTexted()
}

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState(SESSION_DIR)
  const { version } = await fetchLatestBaileysVersion()

  sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: 'silent' }),
    printQRInTerminal: false,
    browser: ['Ubuntu', 'Chrome', '22.04'],
    connectTimeoutMs: 60000,
    retryRequestDelayMs: 2000,
  })

  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      qrAvailable = true
      await QRCode.toFile(QR_PATH, qr, { width: 512, margin: 2 })
      console.log('[wa] QR ready at', QR_PATH)
    }

    if (connection === 'open') {
      isConnected = true
      qrAvailable = false
      connectedPhone = sock.user?.id?.split(':')[0] ?? null
      if (fs.existsSync(QR_PATH)) fs.unlinkSync(QR_PATH)
      console.log('[wa] Connected as', connectedPhone)
    }

    if (connection === 'close') {
      isConnected = false
      const code = lastDisconnect?.error?.output?.statusCode
      console.log('[wa] Disconnected, code:', code)
      if (code !== DisconnectReason.loggedOut) {
        console.log('[wa] Reconnecting in 5s...')
        setTimeout(connect, 5000)
      } else {
        console.log('[wa] Logged out — delete session dir to re-pair')
      }
    }
  })

  sock.ev.on('contacts.upsert', upsertContacts)
  sock.ev.on('contacts.update', upsertContacts)

  sock.ev.on('messages.upsert', ({ messages, type }) => {
    if (type !== 'notify') return
    for (const msg of messages) {
      if (!msg.message) continue
      const remoteJid = msg.key.remoteJid
      if (remoteJid && !msg.key.fromMe && msg.pushName) {
        const phone = remoteJid.split('@')[0]
        if (!contacts.has(remoteJid)) {
          contacts.set(remoteJid, { name: msg.pushName, phone })
          saveContacts()
        }
      }
      const text =
        msg.message.conversation ||
        msg.message.extendedTextMessage?.text ||
        msg.message.imageMessage?.caption ||
        ''
      // capture quoted/replied-to message text for context
      const q = msg.message.extendedTextMessage?.contextInfo?.quotedMessage
      const quoted = q
        ? (q.conversation || q.extendedTextMessage?.text ||
           q.imageMessage?.caption || q.documentMessage?.caption || '')
        : ''
      const entry = {
        id: msg.key.id,
        from: remoteJid,
        fromMe: msg.key.fromMe,
        pushName: msg.pushName || null,
        text,
        quoted,
        timestamp: Number(msg.messageTimestamp),
      }
      recentMessages.unshift(entry)
      if (recentMessages.length > MAX_MESSAGES) recentMessages.pop()
      fs.appendFileSync(MESSAGES_FILE, JSON.stringify(entry) + '\n')

      // auto-reply to incoming from texted contacts
      handleIncoming(msg).catch(console.error)
    }
  })
}

// ── API ──────────────────────────────────────────────

app.get('/status', (req, res) => {
  res.json({ connected: isConnected, phone: connectedPhone, qrReady: qrAvailable })
})

app.get('/qr', (req, res) => {
  if (isConnected) return res.status(409).json({ error: 'already_connected', phone: connectedPhone })
  if (!qrAvailable || !fs.existsSync(QR_PATH)) return res.status(404).json({ error: 'qr_not_ready_yet' })
  res.json({ path: QR_PATH })
})

app.get('/groups', async (req, res) => {
  if (!isConnected) return res.status(503).json({ error: 'not_connected' })
  try {
    const all = await sock.groupFetchAllParticipating()
    const list = Object.values(all).map(g => ({ id: g.id, subject: g.subject }))
    res.json(list)
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

app.post('/send', async (req, res) => {
  const { phone, message, name } = req.body
  if (!isConnected) return res.status(503).json({ error: 'not_connected' })
  if (!phone || !message) return res.status(400).json({ error: 'phone and message required' })
  try {
    const targetJid = jid(phone)
    await sock.sendMessage(targetJid, { text: message })
    // track that we've texted this contact
    if (!textedContacts.has(targetJid)) {
      textedContacts.set(targetJid, 0)
      saveTexted()
    }
    // mirror to history group
    if (targetJid !== LOG_GROUP) {
      const contactName = name || contacts.get(targetJid)?.name || phone
      // also store name in contacts map if provided
      if (name && !contacts.has(targetJid)) {
        contacts.set(targetJid, { name, phone })
        saveContacts()
      }
      logToGroup(`📤 To *${contactName}* (+${phone}):\n${message}`)
    }
    res.json({ ok: true })
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

app.post('/send-group', async (req, res) => {
  const { groupId, message } = req.body
  if (!isConnected) return res.status(503).json({ error: 'not_connected' })
  if (!groupId || !message) return res.status(400).json({ error: 'groupId and message required' })
  try {
    await sock.sendMessage(jid(groupId), { text: message })
    res.json({ ok: true })
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

app.post('/send-file', async (req, res) => {
  const { phone, groupId, filePath, caption = '' } = req.body
  if (!isConnected) return res.status(503).json({ error: 'not_connected' })
  if ((!phone && !groupId) || !filePath) return res.status(400).json({ error: 'phone or groupId, and filePath required' })
  if (!fs.existsSync(filePath)) return res.status(404).json({ error: 'file not found' })
  try {
    const ext = path.extname(filePath).toLowerCase()
    const isImage = ['.jpg', '.jpeg', '.png', '.gif', '.webp'].includes(ext)
    const payload = isImage
      ? { image: fs.readFileSync(filePath), caption }
      : { document: fs.readFileSync(filePath), fileName: path.basename(filePath), caption }
    const target = groupId ? groupId : jid(phone)
    await sock.sendMessage(target, payload)
    if (target !== LOG_GROUP) {
      const contactName = phone ? (contacts.get(jid(phone))?.name || phone) : groupId
      const displayPhone = phone ? ` (+${phone})` : ''
      logToGroup(`📤 File to *${contactName}*${displayPhone}: ${path.basename(filePath)}`)
    }
    res.json({ ok: true })
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

app.get('/messages', (req, res) => {
  const limit = Math.min(parseInt(req.query.limit) || 20, MAX_MESSAGES)
  const from = req.query.from
  const msgs = from
    ? recentMessages.filter(m => m.from === jid(from) || m.from === from)
    : recentMessages
  res.json(msgs.slice(0, limit))
})

app.get('/contacts', (req, res) => {
  const list = Array.from(contacts.values())
    .filter(c => c.name)
    .sort((a, b) => a.name.localeCompare(b.name))
  res.json({ count: list.length, contacts: list })
})

app.get('/contacts/search', (req, res) => {
  const q = (req.query.q || '').toLowerCase()
  if (!q) return res.status(400).json({ error: 'q param required' })
  const results = Array.from(contacts.values()).filter(c =>
    c.name?.toLowerCase().includes(q) || c.phone?.includes(q))
  res.json(results)
})

app.get('/contacts/check', async (req, res) => {
  const { phone } = req.query
  if (!phone) return res.status(400).json({ error: 'phone required' })
  if (!isConnected) return res.status(503).json({ error: 'not_connected' })
  try {
    const results = await sock.onWhatsApp(phone.replace(/\D/g, ''))
    res.json(results)
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

app.get('/profile-picture', async (req, res) => {
  if (!isConnected) return res.status(503).json({ error: 'not_connected' })
  try {
    const targetJid = req.query.phone ? jid(req.query.phone) : sock.user.id
    const url = await sock.profilePictureUrl(targetJid, 'image')
    res.json({ url })
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

app.delete('/session', (req, res) => {
  fs.rmSync(SESSION_DIR, { recursive: true, force: true })
  fs.mkdirSync(SESSION_DIR)
  res.json({ ok: true, message: 'Session cleared. Restart container to re-pair.' })
})

app.listen(3001, '0.0.0.0', () => console.log('[wa] API listening on :3001'))

connect().catch(console.error)
