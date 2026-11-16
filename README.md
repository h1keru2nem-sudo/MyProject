# 🛡️ Qalqan AI — Bilingual Multimodal Anti-Fraud Assistant & Family Alert System

**Qalqan AI** (*"Qalqan"* — *"Shield"* in Kazakh) is a real-time, privacy-first Telegram cybersecurity assistant designed to protect users and families in Kazakhstan from social engineering, phishing, fake banking receipts, and voice-based scams in **Russian** and **Kazakh**.

---

## 🎯 Problem Statement
Financial fraud and social engineering attacks targeting citizens in Kazakhstan (impersonating **Kaspi.kz**, **1414 / eGov**, **Kazpost**, the **National Bank**, or *"relatives in trouble"*) frequently rely on urgency and psychological pressure. Victims often transfer funds or share SMS verification codes before consulting family members.

**Qalqan AI** acts as an immediate, accessible first line of defense directly inside Telegram—requiring zero app installations—and bridges the gap between vulnerable users and their relatives via automated **Family Alerts**.

---

## ✨ Key Features

* **Multimodal Threat Analysis:**
  * **Text & Links:** Detects phishing domains, social engineering scripts, and urgent manipulation tactics in Russian, Kazakh, and mixed colloquial speech (*Shala-Kazakh*).
  * **Screenshots & Receipts (In-Memory OCR):** Extracts text locally using **Tesseract OCR (`rus+kaz+eng`)** to analyze suspicious chats, SMS notifications, and forged payment receipts without sending raw images to external vision APIs.
  * **Voice Messages & Video Notes:** Transcribes audio notes and Telegram video circles (`voice`, `video_note`, `video`) via **Whisper Large v3 Turbo** with custom Kazakh/Russian domain prompting.
* **Context-Aware Reasoning (Short-Term RAM Memory):** Maintains a sliding context window (up to 8 turns, 15-minute TTL) in volatile memory so follow-up clarifications are evaluated holistically rather than in isolation.
* **👨‍👩‍👧‍👦 Family Alert System:** One-click deep-link pairing (`?start=link_<guardian_id>`) connects family members. Whenever a user receives a high-risk verdict (`🔴 ОПАСНО / ҚАУІПТІ`), linked relatives receive an instant alert prompting them to call and intervene immediately.
* **Full Bilingual Support (RU / KZ):** Seamless switching between Russian and Kazakh interfaces and LLM system prompts via `/lang`.

---

## 🏗️ System Architecture

```text
Telegram User (RU / KZ) [Text / Screenshot / Voice / Video Note]
       │
       ├──► In-Memory PIL + Tesseract OCR (Local rus+kaz+eng)
       └──► In-Memory BytesIO + Whisper Large v3 Turbo
       │
       ▼
Short-Term Context Window (RAM, 8 turns, 15m TTL)
       │
       ▼
Groq LPU Inference Engine (Llama 3.3 70B Versatile)
       │
       ├──► Verdict & Guidance (🟢 Safe / 🟡 Caution / 🔴 Danger)
       └──► If HIGH RISK (🔴) ──► SQLite Graph Lookup ──► Instant Family Alert