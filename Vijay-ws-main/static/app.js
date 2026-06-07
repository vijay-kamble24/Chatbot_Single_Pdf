// Application State
let activePDFName = null;
let currentChatHistory = [];
let activeSources = [];
let pollingInterval = null;
let statsInterval = null;
let shouldAutoScroll = true;

const AUTO_SCROLL_THRESHOLD_PX = 80;

// DOM Elements
const dragDropZone = document.getElementById("drag-drop-zone");
const pdfFileInput = document.getElementById("pdf-file-input");
const uploadForm = document.getElementById("upload-form");
const uploadSubmitBtn = document.getElementById("upload-submit-btn");
const uploadProgressWrapper = document.getElementById("upload-progress-wrapper");
const uploadProgress = document.getElementById("upload-progress");
const uploadProgressPercent = document.getElementById("upload-progress-percent");

const scanFolderBtn = document.getElementById("scan-folder-btn");
const pdfListContainer = document.getElementById("pdf-list-container");

const chatFeedContainer = document.getElementById("chat-feed-container");
const chatWelcomeScreen = document.getElementById("chat-welcome-screen");
const chatInput = document.getElementById("chat-input");
const chatSubmitBtn = document.getElementById("chat-submit-btn");
const chatForm = document.getElementById("chat-form");
const activePdfTitle = document.getElementById("active-pdf-title");
const activePdfMeta = document.getElementById("active-pdf-meta");
const clearChatBtn = document.getElementById("clear-chat-btn");

// Monitoring elements
const cpuBar = document.getElementById("cpu-bar");
const cpuValue = document.getElementById("cpu-value");
const ramBar = document.getElementById("ram-bar");
const ramValue = document.getElementById("ram-value");
const cpuWarning = document.getElementById("cpu-warning");
const statsDocs = document.getElementById("stats-docs");
const statsChunks = document.getElementById("stats-chunks");
const dbCompleted = document.getElementById("db-completed");
const dbProcessing = document.getElementById("db-processing");
const dbFailed = document.getElementById("db-failed");
const perfIngest = document.getElementById("perf-ingest");
const perfQuery = document.getElementById("perf-query");
const configLlm = document.getElementById("config-llm");
const configEmbed = document.getElementById("config-embed");

// Citation dialog elements
const citationDialog = document.getElementById("citation-dialog");
const modalPdfName = document.getElementById("modal-pdf-name");
const modalPageNum = document.getElementById("modal-page-num");
const modalCitationContent = document.getElementById("modal-citation-content");
const closeModalBtn = document.getElementById("close-modal-btn");
const modalConfirmCloseBtn = document.getElementById("modal-confirm-close-btn");

// Init Application
document.addEventListener("DOMContentLoaded", () => {
  loadFileList();
  loadStats();

  // Setup intervals
  statsInterval = setInterval(loadStats, 3000);

  // Event listeners
  setupDragAndDrop();
  setupUploadForm();

  scanFolderBtn.addEventListener("click", triggerFolderScan);
  clearChatBtn.addEventListener("click", clearChat);
  chatForm.addEventListener("submit", handleChatSubmit);

  // Keep auto-scroll enabled only while user is near the bottom.
  chatFeedContainer.addEventListener("scroll", () => {
    const distanceFromBottom = chatFeedContainer.scrollHeight - chatFeedContainer.scrollTop - chatFeedContainer.clientHeight;
    shouldAutoScroll = distanceFromBottom <= AUTO_SCROLL_THRESHOLD_PX;
  });

  // Adjust input height dynamically based on content
  chatInput.addEventListener("input", () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = (chatInput.scrollHeight) + 'px';
  });

  // Handle Enter to submit, Shift+Enter for newlines
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!chatSubmitBtn.disabled && chatInput.value.trim()) {
        chatForm.requestSubmit();
      }
    }
  });

  // Dialog closing events
  closeModalBtn.addEventListener("click", () => citationDialog.close());
  modalConfirmCloseBtn.addEventListener("click", () => citationDialog.close());

  // Close dialog when clicking outside the boundary natively
  citationDialog.addEventListener("click", (e) => {
    const rect = citationDialog.getBoundingClientRect();
    const isInDialog = (rect.top <= e.clientY && e.clientY <= rect.top + rect.height &&
                        rect.left <= e.clientX && e.clientX <= rect.left + rect.width);
    if (!isInDialog) {
      citationDialog.close();
    }
  });
});

function scrollChatToBottom(force = false) {
  if (!force && !shouldAutoScroll) return;

  // Run after paint so streamed content growth is included.
  requestAnimationFrame(() => {
    chatFeedContainer.scrollTop = chatFeedContainer.scrollHeight;
  });
}

// Toast System
function showToast(message, type = "success") {
  const toastContainer = document.getElementById("toast-root");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span>${message}</span>
    <span class="toast-close" style="cursor:pointer; font-weight:bold;">&times;</span>
  `;
  
  toast.querySelector(".toast-close").addEventListener("click", () => {
    toast.remove();
  });
  
  toastContainer.appendChild(toast);
  
  // Auto-remove toast after 4 seconds
  setTimeout(() => {
    toast.remove();
  }, 4000);
}

// Drag & Drop Setup
function setupDragAndDrop() {
  const preventDefaults = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };
  
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dragDropZone.addEventListener(eventName, preventDefaults, false);
  });
  
  ['dragenter', 'dragover'].forEach(eventName => {
    dragDropZone.addEventListener(eventName, () => dragDropZone.classList.add("dragover"), false);
  });
  
  ['dragleave', 'drop'].forEach(eventName => {
    dragDropZone.addEventListener(eventName, () => dragDropZone.classList.remove("dragover"), false);
  });
  
  dragDropZone.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files.length > 0 && files[0].name.toLowerCase().endswith('.pdf')) {
      pdfFileInput.files = files;
      updateFileInputLabel(files[0].name);
    } else {
      showToast("Only PDF files are supported.", "error");
    }
  });
  
  pdfFileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      updateFileInputLabel(e.target.files[0].name);
    }
  });
}

function updateFileInputLabel(filename) {
  const textEl = dragDropZone.querySelector(".drop-zone-text");
  textEl.textContent = `Selected: ${filename}`;
  uploadSubmitBtn.disabled = false;
}

// Upload Form Handler
function setupUploadForm() {
  uploadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    
    const file = pdfFileInput.files[0];
    if (!file) return;
    
    // UI states
    uploadSubmitBtn.disabled = true;
    uploadProgressWrapper.style.display = "block";
    uploadProgress.value = 30;
    uploadProgressPercent.textContent = "30%";
    
    const formData = new FormData();
    formData.append("file", file);
    
    try {
      uploadProgress.value = 60;
      uploadProgressPercent.textContent = "60%";
      
      const response = await fetch("/api/pdf/upload", {
        method: "POST",
        body: formData
      });
      
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || "Failed to upload file");
      }
      
      const data = await response.json();
      uploadProgress.value = 100;
      uploadProgressPercent.textContent = "100%";
      
      showToast(`Uploaded ${data.filename} successfully! Ingestion queued.`);
      
      // Reset form
      uploadForm.reset();
      dragDropZone.querySelector(".drop-zone-text").textContent = "Drag & drop PDF here or click to browse";
      
      // Load file list to display processing status
      loadFileList();
      
      // Hide progress container after 2 seconds
      setTimeout(() => {
        uploadProgressWrapper.style.display = "none";
      }, 2000);
              scrollChatToBottom();
    } catch (err) {
      showToast(err.message, "error");
      uploadSubmitBtn.disabled = false;
      uploadProgressWrapper.style.display = "none";
              scrollChatToBottom();
    }
  });
}

// Ingest Directories
async function triggerFolderScan() {
  scanFolderBtn.disabled = true;
  try {
    const response = await fetch("/api/pdf/ingest-folder", {
      method: "POST"
    });
    
    if (!response.ok) throw new Error("Failed to scan directory");
    
    const data = await response.json();
    showToast(data.message);
    
    // Reload files list
    loadFileList();
    
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    setTimeout(() => {
      scanFolderBtn.disabled = false;
    }, 2000);
  }
    shouldAutoScroll = true;
}

// Load List of Files
async function loadFileList() {
  try {
    const response = await fetch("/api/pdf/files");
    if (!response.ok) throw new Error("Failed to fetch documents registry");
    
    const files = await response.json();
    renderFileList(files);
    
    // Check if any file is in PROCESSING state
    const isProcessing = files.some(f => f.status === "PROCESSING" || f.status === "PENDING");
    
    if (isProcessing) {
      // Start rapid polling if not already running
      if (!pollingInterval) {
        pollingInterval = setInterval(loadFileList, 3000);
      }
    } else {
      // Stop polling when nothing is processing
      if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
      }
    }
  } catch (err) {
    console.error("Error loading files:", err);
  }
}

function renderFileList(files) {
  pdfListContainer.innerHTML = "";
  
  if (files.length === 0) {
    pdfListContainer.innerHTML = `<div class="no-files">No documents processed yet. Click Scan Folder or upload a PDF.</div>`;
    return;
  }
  
  files.forEach(file => {
    const fileCard = document.createElement("div");
    fileCard.className = `file-card ${activePDFName === file.name ? 'active' : ''}`;
    fileCard.dataset.name = file.name;
    
    let badgeClass = "badge-pending";
    if (file.status === "COMPLETED") badgeClass = "badge-completed";
    else if (file.status === "PROCESSING") badgeClass = "badge-processing";
    else if (file.status === "FAILED") badgeClass = "badge-failed";
    
    const chunksText = file.total_chunks > 0 ? `${file.total_chunks} chunks` : 'Processing...';
    
    fileCard.innerHTML = `
      <div class="file-name" title="${file.name}">${file.name}</div>
      <div class="file-details-row">
        <span class="folder-badge">/${file.folder_name}</span>
        <span class="badge ${badgeClass}">${file.status}</span>
      </div>
      <div style="font-size: 10px; color: var(--text-muted); display:flex; justify-content:space-between; margin-top:2px;">
        <span>${chunksText}</span>
        <span>${new Date(file.updated_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
      </div>
    `;
    
    // Only allow selection of COMPLETED files
    if (file.status === "COMPLETED") {
      fileCard.addEventListener("click", () => selectActivePDF(file.name, file.total_chunks));
    } else {
      fileCard.style.cursor = "not-allowed";
      if (file.status === "FAILED") {
        fileCard.title = `Ingestion Failed: ${file.error_message}`;
      } else {
        fileCard.title = "Processing Document... Please wait.";
      }
    }
    
    pdfListContainer.appendChild(fileCard);
  });
}

// Select Target PDF
function selectActivePDF(pdfName, totalChunks) {
  activePDFName = pdfName;
  
  // Highlight active card
  document.querySelectorAll(".file-card").forEach(card => {
    if (card.dataset.name === pdfName) {
      card.classList.add("active");
    } else {
      card.classList.remove("active");
    }
  });
  
  // Update header UI
  activePdfTitle.textContent = pdfName;
  activePdfMeta.textContent = `Scope locked to this document. Database chunks: ${totalChunks}. Answers will be grounded only from this file.`;
  
  // Enable Input area
  chatInput.disabled = false;
  chatInput.placeholder = `Ask anything about ${pdfName}...`;
  chatSubmitBtn.disabled = false;
  clearChatBtn.style.display = "inline-flex";
  
  // Clear conversation state for new document scope
  clearChat();
}

// Clear Chat Feed
function clearChat() {
  chatFeedContainer.innerHTML = "";
  currentChatHistory = [];
  activeSources = [];
  shouldAutoScroll = true;
  chatWelcomeScreen.style.display = "none";
  
  if (!activePDFName) {
    chatWelcomeScreen.style.display = "flex";
    chatInput.disabled = true;
    chatInput.placeholder = "Select a document to begin chatting";
    chatSubmitBtn.disabled = true;
    clearChatBtn.style.display = "none";
  }
}

// Render Markdown formatting (simplified)
function formatMessageText(text) {
  if (!text) return "";
  
  // Clean escaping issues
  let formatted = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
    
  // Bold formatting **text**
  formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  
  // Code snippets `code`
  formatted = formatted.replace(/`(.*?)`/g, '<code>$1</code>');
  
  // Paragraph splits
  formatted = formatted.replace(/\n\n/g, '</p><p>');
  
  // Citations mapping [Page X] or [Page X, Y] or [page X]
  // Generates clickable span elements
  formatted = formatted.replace(/\[[Pp]age\s*(\d+)\]/g, (match, pageNum) => {
    return `<span class="citation-tag" onclick="viewCitation(${pageNum})">[Page ${pageNum}]</span>`;
  });
  
  return `<p>${formatted}</p>`;
}

// Append message bubbles to chat
function appendMessage(sender, text, isStreaming = false) {
  chatWelcomeScreen.style.display = "none";
  
  let msgBlock = null;
  
  // If streaming and we are updating the last bubble, retrieve it
  if (isStreaming && sender === "assistant") {
    const lastMsg = chatFeedContainer.lastElementChild;
    if (lastMsg && lastMsg.classList.contains("message-assistant") && !lastMsg.classList.contains("indicator-msg")) {
      msgBlock = lastMsg;
    }
  }
  
  if (!msgBlock) {
    msgBlock = document.createElement("div");
    msgBlock.className = `message message-${sender}`;
    msgBlock.innerHTML = `
      <span class="msg-sender">${sender}</span>
      <div class="message-bubble">
        <div class="bubble-content"></div>
      </div>
    `;
    chatFeedContainer.appendChild(msgBlock);
  }
  
  const contentEl = msgBlock.querySelector(".bubble-content");
  if (isStreaming) {
    contentEl.innerHTML = formatMessageText(text);
  } else {
    contentEl.innerHTML = formatMessageText(text);
  }
  
  // Scroll to bottom when auto-scroll is active.
  scrollChatToBottom();
  return msgBlock;
}

// Show Typing Indicator
function showTypingIndicator() {
  const indicator = document.createElement("div");
  indicator.className = "message message-assistant indicator-msg";
  indicator.innerHTML = `
    <span class="msg-sender">assistant</span>
    <div class="message-bubble" style="padding: 10px;">
      <div class="typing-indicator">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
    </div>
  `;
  chatFeedContainer.appendChild(indicator);
  scrollChatToBottom(true);
  return indicator;
}

// Submit Chat Query (Streaming Response via Fetch ReadableStream)
async function handleChatSubmit(e) {
  e.preventDefault();
  
  const questionText = chatInput.value.trim();
  if (!questionText || !activePDFName) return;
  
  // UI lock
  chatInput.value = "";
  chatInput.style.height = "auto";
  chatInput.disabled = true;
  chatSubmitBtn.disabled = true;
  
  // Append user bubble
  appendMessage("user", questionText);
  
  // Append assistant typing spinner
  const typingIndicator = showTypingIndicator();
  
  let assistantText = "";
  let sourcesReceived = false;
  activeSources = []; // Reset current citations list
  
  try {
    // Call ask API with ReadableStream reading
    const response = await fetch("/api/chat/ask", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        pdf_name: activePDFName,
        question: questionText,
        chat_history: currentChatHistory
      })
    });
    
    // Remove typing indicator
    typingIndicator.remove();
    
    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || "Query execution failed.");
    }
    
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    
    // Create assistant message bubble block
    const assistantBubble = appendMessage("assistant", "", true);
    
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      
      const lines = buffer.split("\n");
      // Keep last incomplete chunk in buffer
      buffer = lines.pop();
      
      for (const line of lines) {
        const cleanLine = line.trim();
        if (!cleanLine.startsWith("data: ")) continue;
        
        const rawJson = cleanLine.substring(6).trim();
        if (rawJson === "[DONE]") {
          break;
        }
        
        try {
          const parsed = JSON.parse(rawJson);
          
          if (parsed.type === "sources") {
            activeSources = parsed.sources;
            renderCitationsInBubble(assistantBubble, parsed.sources);
            sourcesReceived = true;
          } else if (parsed.type === "content") {
            assistantText += parsed.text;
            // Update bubble content
            assistantBubble.querySelector(".bubble-content").innerHTML = formatMessageText(assistantText);
            scrollChatToBottom();
          } else if (parsed.type === "error") {
            showToast(parsed.text, "error");
            assistantText += `\n\n[Error: ${parsed.text}]`;
            assistantBubble.querySelector(".bubble-content").innerHTML = formatMessageText(assistantText);
            scrollChatToBottom();
          }
        } catch (jsonErr) {
          console.error("JSON parsing error:", jsonErr, rawJson);
        }
      }
    }
    
    // Sync to conversation history
    currentChatHistory.push({ role: "user", content: questionText });
    currentChatHistory.push({ role: "assistant", content: assistantText });
    
  } catch (err) {
    typingIndicator.remove();
    showToast(err.message, "error");
    appendMessage("assistant", `I encountered an error trying to search: ${err.message}`);
  } finally {
    chatInput.disabled = false;
    chatSubmitBtn.disabled = false;
    chatInput.focus();
  }
}

// Render Citation Tags below the Assistant message bubble
function renderCitationsInBubble(bubbleElement, sources) {
  if (!sources || sources.length === 0) return;
  
  // Check if citations block already exists
  let citationsDiv = bubbleElement.querySelector(".citations-container");
  if (!citationsDiv) {
    citationsDiv = document.createElement("div");
    citationsDiv.className = "citations-container";
    bubbleElement.appendChild(citationsDiv);
  }
  
  citationsDiv.innerHTML = `<span style="font-size:11px; color:var(--text-muted); font-weight:600; width:100%; display:block; margin-bottom:4px;">Grounded Sources:</span>`;
  
  // Render unique page tags
  const uniquePages = [...new Set(sources.map(s => s.page_number))].sort((a, b) => a - b);
  
  uniquePages.forEach(pageNum => {
    const tag = document.createElement("span");
    tag.className = "citation-tag";
    tag.textContent = `Page ${pageNum}`;
    tag.addEventListener("click", () => viewCitation(pageNum));
    citationsDiv.appendChild(tag);
  });

  scrollChatToBottom();
}

// View Citation Details in Native Modal Dialog
function viewCitation(pageNumber) {
  // Find source matching this page number
  const source = activeSources.find(s => s.page_number === pageNumber);
  
  if (!source) {
    showToast(`No snippet cached for Page ${pageNumber}.`, "warning");
    return;
  }
  
  // Populate native modal dialog elements
  modalPdfName.textContent = source.pdf_name;
  modalPageNum.textContent = `Page ${source.page_number}`;
  modalCitationContent.textContent = source.snippet;
  
  // Show dialog using standard native browser API
  citationDialog.showModal();
}

// Load Monitoring Stats
async function loadStats() {
  try {
    const response = await fetch("/api/monitoring/stats");
    if (!response.ok) throw new Error("Failed to fetch monitoring stats");
    
    const data = await response.json();
    
    // Update resources visuals
    const cpu = data.system.cpu_percent;
    const ram = data.system.memory_percent;
    
    cpuBar.style.width = `${cpu}%`;
    cpuValue.textContent = `${cpu}%`;
    
    ramBar.style.width = `${ram}%`;
    ramValue.textContent = `${ram}%`;
    
    // Warn if CPU exceeds 50%
    if (cpu > 50) {
      cpuWarning.style.display = "block";
      cpuBar.style.setProperty("--bar-color", "var(--error)");
    } else {
      cpuWarning.style.display = "none";
      cpuBar.style.setProperty("--bar-color", "var(--success)");
    }
    
    // Update DB counts
    statsDocs.textContent = data.database.total_documents;
    statsChunks.textContent = data.database.total_chunks;
    
    dbCompleted.textContent = data.database.completed_documents;
    dbProcessing.textContent = data.database.processing_documents;
    dbFailed.textContent = data.database.failed_documents;
    
    // Update Latencies
    perfIngest.textContent = `${data.performance.avg_ingestion_seconds}s`;
    perfQuery.textContent = `${data.performance.avg_query_seconds}s`;
    
    // Update config info
    configLlm.textContent = data.configuration.llm_provider;
    configEmbed.textContent = data.configuration.embedding_provider;
    
  } catch (err) {
    console.error("Error updating statistics dashboard:", err);
  }
}
