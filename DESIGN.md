# Design System & UI/UX Specifications
## DocuChat AI — Visual Design & Frontend Architecture

---

## 1. Design Philosophy
DocuChat AI adheres to a modern, dark-mode-first aesthetic inspired by linear and modern generative AI workstations. The interface balances high information density with sleek visual hierarchy, glassmorphism, subtle glowing accents, and fluid micro-animations.

---

## 2. Color Palette & Token Architecture

All colors are controlled via CSS custom properties in `frontend/src/App.css`:

```css
:root {
  /* Surfaces & Backgrounds */
  --bg-primary: #0a0d14;    /* Deep obsidian canvas background */
  --bg-secondary: #101522;  /* Cards, input container, panels */
  --bg-tertiary: #182032;   /* Hover states, control buttons */
  --border-color: rgba(255, 255, 255, 0.08); /* Crisp subtle border */

  /* Typography */
  --text-main: #f1f5f9;     /* High contrast primary text */
  --text-muted: #94a3b8;    /* Secondary metadata, subtitles */
  --text-sub: #64748b;      /* Tertiary hints, timestamps */

  /* Vibrant Accents */
  --accent-indigo: #9c28ef; /* Primary brand purple */
  --accent-violet: #5819e9; /* Deep electric violet */
  --accent-emerald: #10b981;/* Document badge, ready status */
  --accent-amber: #f59e0b;  /* Processing warning, citations */
  --accent-rose: #f43f5e;   /* Error badge, destructive actions */
}
```

---

## 3. Layout Architecture (The 3-Panel Grid)

```text
+---------------------------------------------------------------------------------------------------+
|                                      DOCUCHAT AI WORKSTATION                                       |
+----------------------+----------------------------------------------------+-----------------------+
|  LEFT SIDEBAR (260px)|              CENTER CHAT PANEL (Flex: 1)           | RIGHT VIEWER (420px)  |
|                      |                                                    |                       |
|  [⚡ DocuChat AI]     |  [Header: Title | Scope Selector | ⚙️ | Hide]       |  [Toolbar: < 1/1 >]   |
|                      |                                                    |                       |
|  [+ New Chat Ctrl+K] |  Message Stream:                                   |  +-----------------+  |
|                      |  [User Bubble: "intermediate percentage"]          |  | HTML5 Canvas    |  |
|  Tabs: Chats | Docs  |                                                    |  | PDF Rendering   |  |
|                      |  [AI Bubble: [📄 From document]                    |  |                 |  |
|  • Chat 1            |   "The intermediate percentage is 81%." [1] ]     |  | [=== Highlight] |  |
|  • Chat 2            |                                                    |  |  (Single Box)   |  |
|  • cv.pdf (Ready)    |  +-----------------------------------------------+ |  +-----------------+  |
|                      |  | [🌐 ChatGPT Mode / 📄 cv.pdf]                 | |                       |
|                      |  | [Textarea: "Ask questions..."]      [ Send ➔ ]| |  Citations Drawer:    |
|                      |  +-----------------------------------------------+ |  [1] Page 1: 81%...   |
+----------------------+----------------------------------------------------+-----------------------+
```

### 3.1 Left Sidebar (`.left-sidebar`)
- Fixed width: `260px` with collapsible drawer support on mobile viewports.
- Segmented tabs: Switch between **Chats (Sessions)** and **Documents (Ingested files)**.
- Quick shortcut indicator: `Ctrl+K` for instant new conversation creation.

### 3.2 Center Chat Area (`.center-chat`)
- Dynamic header containing the conversational title, real-time scope selector (`All Documents`, individual file, or `🌐 ChatGPT Mode`), and toggle buttons.
- Message stream rendering markdown tables, code snippets, and interactive `[1]` citation pills.
- Floating input container featuring dynamic mode chips, upload attachment trigger, and smooth auto-expanding textarea.

### 3.3 Right PDF Viewer (`.right-viewer`)
- Collapsible canvas sidebar (`420px` default width, expandable/collapsible via the `Hide` header toggle).
- Integrated PDF.js canvas with an absolute bounding box overlay layer.
- Bottom citations drawer displaying thumbnail snippets and page indicators.

---

## 4. Key Component Specifications

### 4.1 Citation Pills (`.citation-pill`)
- **Appearance:** Rounded badge (`10px` radius) with subtle glowing border:
  `background: rgba(99, 102, 241, 0.2); color: #818cf8;`
- **Interaction:** Hovering lifts the pill slightly (`transform: scale(1.05)`). Clicking immediately opens the PDF viewer, scrolls to the cited page, and animates the matching bounding box.

### 4.2 Single-Answer Bounding Box (`.highlight-rect.focused`)
- **Style:** Glowing indigo/amber rectangle aligned directly to the PDF coordinates:
  ```css
  .highlight-rect.focused {
    background: rgba(99, 102, 241, 0.38);
    border: 2px solid #6366f1;
    box-shadow: 0 0 16px rgba(99, 102, 241, 0.8);
    animation: pulseHighlight 1.5s infinite;
  }
  ```
- **Pulse Micro-Animation:** Gently expands and contracts (`scale(1)` to `scale(1.02)`) to draw user focus without obscuring the underlying document typography.

### 4.3 Mode Badges (`.router-badge`)
- **Document Grounded:** `background: rgba(16, 185, 129, 0.15); color: #34d399;` (`📄 From document`)
- **ChatGPT Real-World:** `background: rgba(99, 102, 241, 0.15); color: #a5b4fc;` (`✨ General answer`)

---

## 5. Responsive Behavior
- **Desktop ($\ge 1200\text{px}$):** Complete 3-panel split view with full PDF canvas visible alongside chat.
- **Laptop / Tablet ($768\text{px} - 1199\text{px}$):** PDF viewer collapses to drawer format; opens on citation click.
- **Mobile ($< 768\text{px}$):** Single-column stacked layout with slide-out sidebar drawer.
