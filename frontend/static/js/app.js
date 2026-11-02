/**
 * Ajaia Collaborative Document Editor - Frontend Application Logic
 *
 * Implements Google Docs-inspired rich text editing with Quill.js, persona switching,
 * real-time debounced autosave with race-condition prevention (saveQueued + flushPendingSave),
 * batch file ingestion (up to 20MB), MinIO raw downloads, and Markdown/Text exports.
 */

document.addEventListener("DOMContentLoaded", () => {
  // ----------------------------------------------------
  // Security Helper: DOM-XSS Escaping
  // ----------------------------------------------------
  /**
   * Escape untrusted text for safe HTML string interpolation.
   * @param {string} str
   * @returns {string}
   */
  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // ----------------------------------------------------
  // Application State
  // ----------------------------------------------------
  const state = {
    activeUser: {
      email: localStorage.getItem("ajaia_active_user_email") || "alice@ajaia.test",
      name: localStorage.getItem("ajaia_active_user_name") || "Alice Johnson",
    },
    users: [],
    currentDoc: null,
    saveDebounceTimer: null,
    isSaving: false,
    saveQueued: false,
    hasPendingChanges: false,
  };

  // ----------------------------------------------------
  // DOM Elements
  // ----------------------------------------------------
  const dashboardView = document.getElementById("dashboardView");
  const editorView = document.getElementById("editorView");
  const navDocControls = document.getElementById("navDocControls");
  const docTitleInput = document.getElementById("docTitleInput");
  const saveStatus = document.getElementById("saveStatus");
  const permissionBadge = document.getElementById("permissionBadge");
  const btnOpenShare = document.getElementById("btnOpenShare");
  const activePersonaName = document.getElementById("activePersonaName");
  const activePersonaBadge = document.getElementById("activePersonaBadge");
  const personaList = document.getElementById("personaList");

  const ownedDocsGrid = document.getElementById("ownedDocsGrid");
  const sharedDocsGrid = document.getElementById("sharedDocsGrid");
  const badgeOwnedCount = document.getElementById("badgeOwnedCount");
  const badgeSharedCount = document.getElementById("badgeSharedCount");

  const btnCreateDoc = document.getElementById("btnCreateDoc");
  const btnBackToDashboard = document.getElementById("btnBackToDashboard");
  const btnDeleteDoc = document.getElementById("btnDeleteDoc");
  const btnDownloadRawLink = document.getElementById("btnDownloadRawLink");
  const btnExportMd = document.getElementById("btnExportMd");
  const btnExportTxt = document.getElementById("btnExportTxt");
  const btnExportHtml = document.getElementById("btnExportHtml");
  const docMetaInfo = document.getElementById("docMetaInfo");
  const brandLink = document.getElementById("brandLink");

  // Share Modal elements
  const shareModal = new bootstrap.Modal(document.getElementById("shareModal"));
  const shareModalDocTitle = document.getElementById("shareModalDocTitle");
  const shareForm = document.getElementById("shareForm");
  const shareEmailInput = document.getElementById("shareEmailInput");
  const sharePermissionSelect = document.getElementById("sharePermissionSelect");
  const shareAccessList = document.getElementById("shareAccessList");
  const quickPickBob = document.getElementById("quickPickBob");
  const quickPickAlice = document.getElementById("quickPickAlice");

  // File Upload elements
  const uploadModal = new bootstrap.Modal(document.getElementById("uploadModal"));
  const modalFileInput = document.getElementById("modalFileInput");
  const btnSubmitUpload = document.getElementById("btnSubmitUpload");
  const uploadProgress = document.getElementById("uploadProgress");
  const quickDropzone = document.getElementById("quickDropzone");
  const dragFileInput = document.getElementById("dragFileInput");

  // Toast
  const toastEl = document.getElementById("appToast");
  const toastMessage = document.getElementById("toastMessage");
  const toast = new bootstrap.Toast(toastEl, { delay: 3500 });

  function showToast(msg, isError = false) {
    toastMessage.textContent = msg;
    toastEl.className = `toast align-items-center text-white ${isError ? "bg-danger" : "bg-dark"} border-0 shadow`;
    toast.show();
  }

  // ----------------------------------------------------
  // HTTP Fetch Wrapper with Persona Header
  // ----------------------------------------------------
  /**
   * Execute an authenticated API request with X-User-Email header.
   * @param {string} url
   * @param {RequestInit} [options={}]
   * @returns {Promise<any>}
   */
  async function apiFetch(url, options = {}) {
    const headers = {
      "X-User-Email": state.activeUser.email,
      ...(options.headers || {}),
    };
    if (options.body && !(options.body instanceof FormData) && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }

    try {
      const response = await fetch(url, { ...options, headers });
      if (response.status === 204) {
        return null;
      }
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        const errorDetail = data?.detail || `Request failed with status ${response.status}`;
        throw new Error(errorDetail);
      }
      return data;
    } catch (err) {
      console.error(`API Error on ${url}:`, err);
      throw err;
    }
  }

  // ----------------------------------------------------
  // Quill Editor Initialization
  // ----------------------------------------------------
  const quill = new Quill("#quillEditor", {
    modules: {
      toolbar: "#quillToolbar",
    },
    theme: "snow",
    placeholder: "Start typing your document content here...",
  });

  quill.on("text-change", (delta, oldDelta, source) => {
    if (source === "user" && state.currentDoc) {
      scheduleAutoSave();
    }
  });

  docTitleInput.addEventListener("input", () => {
    if (state.currentDoc) {
      scheduleAutoSave();
    }
  });

  /**
   * Debounces document autosaving by 800ms while user is actively typing.
   */
  function scheduleAutoSave() {
    setSaveStatus("saving");
    state.hasPendingChanges = true;
    clearTimeout(state.saveDebounceTimer);
    state.saveDebounceTimer = setTimeout(() => {
      saveCurrentDocument();
    }, 800);
  }

  /**
   * Updates the UI badge displaying cloud sync state.
   * @param {'saving'|'saved'|'error'} status
   */
  function setSaveStatus(status) {
    if (status === "saving") {
      saveStatus.className = "badge rounded-pill bg-light text-warning border px-2 py-1";
      saveStatus.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Saving...';
    } else if (status === "saved") {
      saveStatus.className = "badge rounded-pill bg-light text-muted border px-2 py-1";
      saveStatus.innerHTML = '<i class="bi bi-cloud-check text-success me-1"></i> Saved';
    } else if (status === "error") {
      saveStatus.className = "badge rounded-pill bg-danger-subtle text-danger border px-2 py-1";
      saveStatus.innerHTML = '<i class="bi bi-exclamation-triangle text-danger me-1"></i> Error saving';
    }
  }

  // ----------------------------------------------------
  // Robust Save Implementation (Race-Condition Free)
  // ----------------------------------------------------
  /**
   * Immediately flush any debounced or pending save before view transitions.
   */
  async function flushPendingSave() {
    if (state.saveDebounceTimer) {
      clearTimeout(state.saveDebounceTimer);
      state.saveDebounceTimer = null;
    }
    if (state.hasPendingChanges && state.currentDoc && state.currentDoc.permission !== "view") {
      await saveCurrentDocument();
    }
  }

  /**
   * Persists active document title and HTML content to the backend.
   * Uses state.saveQueued to serialize concurrent in-flight requests.
   */
  async function saveCurrentDocument() {
    if (!state.currentDoc) return;

    if (state.currentDoc.permission === "view") {
      setSaveStatus("saved");
      state.hasPendingChanges = false;
      return;
    }

    // If a save request is already in-flight, mark queued and avoid concurrent collision
    if (state.isSaving) {
      state.saveQueued = true;
      return;
    }

    state.isSaving = true;
    state.saveQueued = false;
    const title = docTitleInput.value.trim() || "Untitled Document";
    const content_html = quill.root.innerHTML;
    const content_text = quill.getText();

    try {
      const updatedDoc = await apiFetch(`/api/v1/documents/${state.currentDoc.id}`, {
        method: "PUT",
        body: JSON.stringify({
          title,
          content_html,
          content_text,
        }),
      });

      state.currentDoc = updatedDoc;
      setSaveStatus("saved");
      state.hasPendingChanges = false;
    } catch (err) {
      setSaveStatus("error");
      showToast(`Save failed: ${err.message}`, true);
    } finally {
      state.isSaving = false;
      // If edits occurred while the previous save was in-flight, execute queued save immediately
      if (state.saveQueued) {
        state.saveQueued = false;
        saveCurrentDocument();
      }
    }
  }

  // Window unload guard to prevent data loss
  window.addEventListener("beforeunload", (e) => {
    if (state.hasPendingChanges) {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  // ----------------------------------------------------
  // User Persona Management
  // ----------------------------------------------------
  async function loadUserPersonas() {
    try {
      const users = await apiFetch("/api/v1/users");
      state.users = users;
      renderPersonaDropdown();
    } catch (err) {
      console.warn("Could not load users:", err);
    }
  }

  function renderPersonaDropdown() {
    personaList.innerHTML = '<li><h6 class="dropdown-header">Switch Test Persona</h6></li>';

    state.users.forEach((u) => {
      const isCurrent = u.email === state.activeUser.email;
      const li = document.createElement("li");
      li.innerHTML = `
        <a class="dropdown-item d-flex align-items-center justify-content-between ${isCurrent ? 'active' : ''}" href="#">
          <div>
            <div class="fw-medium">${escapeHtml(u.name)}</div>
            <div class="small ${isCurrent ? 'text-light' : 'text-muted'}">${escapeHtml(u.email)}</div>
          </div>
          ${isCurrent ? '<i class="bi bi-check-lg ms-2"></i>' : ''}
        </a>
      `;
      li.addEventListener("click", async (e) => {
        e.preventDefault();
        await switchUserPersona(u);
      });
      personaList.appendChild(li);
    });

    activePersonaName.textContent = state.activeUser.name;
    activePersonaBadge.textContent = state.activeUser.email.includes("alice") ? "Owner" : "Reviewer";
  }

  /**
   * Switch the active collaborator persona. Flushes pending saves before switching.
   * @param {{email: string, name: string}} user
   */
  async function switchUserPersona(user) {
    if (user.email === state.activeUser.email) return;

    // Flush any unsaved edits before persona changes
    await flushPendingSave();

    state.activeUser = { email: user.email, name: user.name };
    localStorage.setItem("ajaia_active_user_email", user.email);
    localStorage.setItem("ajaia_active_user_name", user.name);

    renderPersonaDropdown();
    showToast(`Switched active persona to ${user.name}`);

    if (state.currentDoc) {
      await openDocument(state.currentDoc.id);
    } else {
      await loadDocuments();
    }
  }

  // ----------------------------------------------------
  // Dashboard Document List Loading
  // ----------------------------------------------------
  async function loadDocuments() {
    ownedDocsGrid.innerHTML = `
      <div class="col-12 text-center py-5 text-muted">
        <div class="spinner-border spinner-border-sm text-primary" role="status"></div> Loading documents...
      </div>`;
    sharedDocsGrid.innerHTML = "";

    try {
      const data = await apiFetch("/api/v1/documents");
      badgeOwnedCount.textContent = data.owned.length;
      badgeSharedCount.textContent = data.shared.length;

      renderDocumentCards(data.owned, ownedDocsGrid, true);
      renderDocumentCards(data.shared, sharedDocsGrid, false);
    } catch (err) {
      ownedDocsGrid.innerHTML = `<div class="col-12 alert alert-danger">Error loading documents: ${err.message}</div>`;
      showToast(`Error loading documents: ${err.message}`, true);
    }
  }

  function renderDocumentCards(docs, container, isOwnedTab) {
    if (!docs || docs.length === 0) {
      container.innerHTML = `
        <div class="col-12 text-center py-5 text-muted">
          <i class="bi bi-file-earmark-text fs-1 d-block mb-2 text-secondary opacity-50"></i>
          <p class="mb-0">${isOwnedTab ? 'No documents created yet. Click "New Document" or import files above!' : 'No documents shared with you yet.'}</p>
        </div>`;
      return;
    }

    container.innerHTML = "";
    docs.forEach((doc) => {
      const col = document.createElement("div");
      col.className = "col-sm-6 col-md-4 col-lg-3";

      const updatedDate = new Date(doc.updated_at).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      });

      const fileTypeBadge = doc.file_type && doc.file_type !== "native"
        ? `<span class="badge bg-secondary-subtle text-secondary text-uppercase">${escapeHtml(doc.file_type)}</span>`
        : "";

      const permissionPill = isOwnedTab
        ? `<span class="badge bg-light text-muted border">Owner</span>`
        : `<span class="badge ${doc.permission === 'edit' ? 'bg-success-subtle text-success' : 'bg-warning-subtle text-warning'}">${doc.permission === 'edit' ? 'Can Edit' : 'Read Only'}</span>`;

      const safeTitle = escapeHtml(doc.title || "Untitled Document");
      const safeOwner = escapeHtml(doc.owner_name || doc.owner_email || "Unknown");

      col.innerHTML = `
        <div class="card h-100 doc-card shadow-sm border" data-doc-id="${escapeHtml(doc.id)}">
          <div class="doc-icon-preview">
            <i class="bi bi-file-earmark-richtext fs-1 text-primary"></i>
          </div>
          <div class="card-body p-3 d-flex flex-column">
            <h6 class="card-title fw-bold text-dark text-truncate mb-1" title="${safeTitle}">
              ${safeTitle}
            </h6>
            <div class="small text-muted mb-2">
              ${isOwnedTab ? `Updated ${updatedDate}` : `Owner: ${safeOwner}`}
            </div>
            <div class="mt-auto d-flex justify-content-between align-items-center pt-2 border-top">
              <div class="d-flex gap-1 align-items-center">
                ${fileTypeBadge}
                ${permissionPill}
              </div>
              <button class="btn btn-outline-primary btn-sm px-3 py-1">Open</button>
            </div>
          </div>
        </div>
      `;

      col.querySelector(".doc-card").addEventListener("click", async () => {
        await flushPendingSave();
        openDocument(doc.id);
      });

      container.appendChild(col);
    });
  }

  // ----------------------------------------------------
  // Document View & Navigation
  // ----------------------------------------------------
  async function openDocument(docId) {
    try {
      const doc = await apiFetch(`/api/v1/documents/${docId}`);
      state.currentDoc = doc;

      docTitleInput.value = doc.title;

      // Silent Quill clipboard paste to prevent triggering spurious 'text-change' events
      quill.clipboard.dangerouslyPasteHTML(doc.content_html || "", "silent");
      setSaveStatus("saved");
      state.hasPendingChanges = false;

      const isOwner = doc.permission === "owner";
      const canEdit = isOwner || doc.permission === "edit";

      permissionBadge.textContent = isOwner ? "Owner" : (doc.permission === "edit" ? "Editor" : "Viewer (Read-only)");
      permissionBadge.className = `badge ${isOwner ? 'bg-primary-subtle text-primary' : (canEdit ? 'bg-success-subtle text-success' : 'bg-warning-subtle text-warning')}`;

      quill.enable(canEdit);
      docTitleInput.disabled = !canEdit;

      const updatedDate = new Date(doc.updated_at).toLocaleString();
      docMetaInfo.textContent = `Owner: ${escapeHtml(doc.owner_name)} (${escapeHtml(doc.owner_email)}) • Last updated: ${updatedDate}`;

      // Toggle raw download link in Export dropdown
      if (doc.minio_object_key) {
        btnDownloadRawLink.classList.remove("d-none");
      } else {
        btnDownloadRawLink.classList.add("d-none");
      }

      // Delete & Share buttons: Only owner can access
      if (isOwner) {
        btnDeleteDoc.classList.remove("d-none");
        btnDeleteDoc.classList.add("d-flex");
        btnOpenShare.classList.remove("d-none");
        btnOpenShare.classList.add("d-flex");
      } else {
        btnDeleteDoc.classList.add("d-none");
        btnDeleteDoc.classList.remove("d-flex");
        btnOpenShare.classList.add("d-none");
        btnOpenShare.classList.remove("d-flex");
      }

      dashboardView.classList.add("d-none");
      editorView.classList.remove("d-none");
      navDocControls.classList.remove("d-none");

      window.scrollTo(0, 0);
    } catch (err) {
      showToast(`Cannot open document: ${err.message}`, true);
      showDashboard();
    }
  }

  async function showDashboard() {
    await flushPendingSave();
    state.currentDoc = null;
    editorView.classList.add("d-none");
    navDocControls.classList.add("d-none");
    btnOpenShare.classList.add("d-none");
    btnOpenShare.classList.remove("d-flex");
    dashboardView.classList.remove("d-none");
    loadDocuments();
  }

  // ----------------------------------------------------
  // Document Actions (Create, Delete, Export)
  // ----------------------------------------------------
  btnCreateDoc.addEventListener("click", async () => {
    try {
      btnCreateDoc.disabled = true;
      const newDoc = await apiFetch("/api/v1/documents", {
        method: "POST",
        body: JSON.stringify({
          title: "Untitled Document",
          content_html: "<p></p>",
        }),
      });
      showToast("New document created");
      openDocument(newDoc.id);
    } catch (err) {
      showToast(`Failed to create document: ${err.message}`, true);
    } finally {
      btnCreateDoc.disabled = false;
    }
  });

  btnBackToDashboard.addEventListener("click", async () => {
    await showDashboard();
  });

  brandLink.addEventListener("click", async (e) => {
    e.preventDefault();
    await showDashboard();
  });

  btnDeleteDoc.addEventListener("click", async () => {
    if (!state.currentDoc) return;
    if (!confirm(`Are you sure you want to permanently delete "${state.currentDoc.title}"?`)) {
      return;
    }

    try {
      btnDeleteDoc.disabled = true;
      await apiFetch(`/api/v1/documents/${state.currentDoc.id}`, {
        method: "DELETE",
      });
      showToast("Document deleted successfully");
      showDashboard();
    } catch (err) {
      showToast(`Delete failed: ${err.message}`, true);
    } finally {
      btnDeleteDoc.disabled = false;
    }
  });

  // Export handlers
  btnExportMd.addEventListener("click", () => {
    if (!state.currentDoc) return;
    window.location.href = `/api/v1/documents/${state.currentDoc.id}/export?format=md&x_user_email=${encodeURIComponent(state.activeUser.email)}`;
  });

  btnExportTxt.addEventListener("click", () => {
    if (!state.currentDoc) return;
    window.location.href = `/api/v1/documents/${state.currentDoc.id}/export?format=txt&x_user_email=${encodeURIComponent(state.activeUser.email)}`;
  });

  btnExportHtml.addEventListener("click", () => {
    if (!state.currentDoc) return;
    const blob = new Blob([state.currentDoc.content_html || ""], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${state.currentDoc.title || "document"}.html`;
    a.click();
    URL.revokeObjectURL(url);
  });

  btnDownloadRawLink.addEventListener("click", (e) => {
    e.preventDefault();
    if (!state.currentDoc) return;
    window.location.href = `/api/v1/documents/${state.currentDoc.id}/download-raw?x_user_email=${encodeURIComponent(state.activeUser.email)}`;
  });

  // ----------------------------------------------------
  // Sharing Modal & Collaborators
  // ----------------------------------------------------
  btnOpenShare.addEventListener("click", () => {
    if (!state.currentDoc) return;
    shareModalDocTitle.textContent = `Sharing "${state.currentDoc.title}"`;
    renderShareAccessList();
  });

  quickPickBob.addEventListener("click", () => {
    shareEmailInput.value = "bob@ajaia.test";
  });

  quickPickAlice.addEventListener("click", () => {
    shareEmailInput.value = "alice@ajaia.test";
  });

  function renderShareAccessList() {
    if (!state.currentDoc) return;

    let html = `
      <div class="list-group-item d-flex justify-content-between align-items-center px-2 py-2">
        <div>
          <div class="fw-medium text-dark">${escapeHtml(state.currentDoc.owner_name)} (${escapeHtml(state.currentDoc.owner_email)})</div>
          <div class="text-muted small">Owner</div>
        </div>
        <span class="badge bg-primary-subtle text-primary">Owner</span>
      </div>
    `;

    if (state.currentDoc.shares && state.currentDoc.shares.length > 0) {
      state.currentDoc.shares.forEach((s) => {
        html += `
          <div class="list-group-item d-flex justify-content-between align-items-center px-2 py-2">
            <div>
              <div class="fw-medium text-dark">${escapeHtml(s.user_name || s.user_email)}</div>
              <div class="text-muted small">${escapeHtml(s.user_email)} • ${s.permission === 'edit' ? 'Can edit' : 'Can view'}</div>
            </div>
            <button class="btn btn-outline-danger btn-xs py-1 px-2 btn-revoke-share" data-user-id="${escapeHtml(s.user_id)}">
              <i class="bi bi-x-circle"></i> Revoke
            </button>
          </div>
        `;
      });
    } else {
      html += `
        <div class="text-muted text-center py-3 small">
          No collaborators added yet. Invite someone above!
        </div>
      `;
    }

    shareAccessList.innerHTML = html;

    // Attach revoke event handlers
    shareAccessList.querySelectorAll(".btn-revoke-share").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const userId = e.currentTarget.getAttribute("data-user-id");
        await revokeShareAccess(userId);
      });
    });
  }

  shareForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!state.currentDoc) return;

    const email = shareEmailInput.value.trim();
    const permission = sharePermissionSelect.value;
    if (!email) return;

    try {
      const shareRecord = await apiFetch(`/api/v1/documents/${state.currentDoc.id}/shares`, {
        method: "POST",
        body: JSON.stringify({ email, permission }),
      });

      showToast(`Invited ${email} as ${permission}`);
      shareEmailInput.value = "";

      // Refresh current document state to show updated shares list
      const refreshedDoc = await apiFetch(`/api/v1/documents/${state.currentDoc.id}`);
      state.currentDoc = refreshedDoc;
      renderShareAccessList();
    } catch (err) {
      showToast(`Failed to share: ${err.message}`, true);
    }
  });

  async function revokeShareAccess(userId) {
    if (!state.currentDoc) return;
    try {
      await apiFetch(`/api/v1/documents/${state.currentDoc.id}/shares/${userId}`, {
        method: "DELETE",
      });
      showToast("Access revoked");
      const refreshedDoc = await apiFetch(`/api/v1/documents/${state.currentDoc.id}`);
      state.currentDoc = refreshedDoc;
      renderShareAccessList();
    } catch (err) {
      showToast(`Revocation failed: ${err.message}`, true);
    }
  }

  // ----------------------------------------------------
  // Batch File Ingestion (20MB) & MinIO Upload
  // ----------------------------------------------------
  async function handleBatchFileUpload(files) {
    if (!files || files.length === 0) return;

    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
      formData.append("files", files[i]);
    }

    try {
      uploadProgress.classList.remove("d-none");
      btnSubmitUpload.disabled = true;

      const result = await apiFetch("/api/v1/documents/upload", {
        method: "POST",
        body: formData,
      });

      uploadModal.hide();
      modalFileInput.value = "";

      if (Array.isArray(result) && result.length > 1) {
        showToast(`Successfully imported ${result.length} files`);
        await loadDocuments();
      } else {
        const docToOpen = Array.isArray(result) ? result[0] : result;
        showToast(`Imported "${docToOpen.title}"`);
        openDocument(docToOpen.id);
      }
    } catch (err) {
      showToast(`Import failed: ${err.message}`, true);
    } finally {
      uploadProgress.classList.add("d-none");
      btnSubmitUpload.disabled = false;
    }
  }

  btnSubmitUpload.addEventListener("click", () => {
    if (modalFileInput.files.length > 0) {
      handleBatchFileUpload(modalFileInput.files);
    } else {
      showToast("Please choose at least one .md or .txt file", true);
    }
  });

  // Drag and drop quick dropzone
  quickDropzone.addEventListener("click", () => dragFileInput.click());
  dragFileInput.addEventListener("change", () => {
    if (dragFileInput.files.length > 0) {
      handleBatchFileUpload(dragFileInput.files);
    }
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    quickDropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      quickDropzone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    quickDropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      quickDropzone.classList.remove("dragover");
    });
  });

  quickDropzone.addEventListener("drop", (e) => {
    const dt = e.dataTransfer;
    if (dt && dt.files.length > 0) {
      handleBatchFileUpload(dt.files);
    }
  });

  // ----------------------------------------------------
  // Bootstrap Application Initialization
  // ----------------------------------------------------
  loadUserPersonas();
  loadDocuments();
});
