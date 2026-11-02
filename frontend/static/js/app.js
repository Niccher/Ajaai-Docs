/**
 * Ajaia Collaborative Document Editor
 * Frontend Application Logic (Vanilla JS + Bootstrap 5.3 + Quill.js)
 */

document.addEventListener("DOMContentLoaded", () => {
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
  const btnDownloadRaw = document.getElementById("btnDownloadRaw");
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
    toastEl.className = `toast align-items-center text-white ${isError ? 'bg-danger' : 'bg-dark'} border-0 shadow`;
    toast.show();
  }

  // ----------------------------------------------------
  // HTTP Fetch Wrapper with Persona Header
  // ----------------------------------------------------
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

  // Listen to text changes for debounced autosave
  quill.on("text-change", (delta, oldDelta, source) => {
    if (source === "user" && state.currentDoc) {
      scheduleAutoSave();
    }
  });

  // Title change triggers autosave
  docTitleInput.addEventListener("input", () => {
    if (state.currentDoc) {
      scheduleAutoSave();
    }
  });

  function scheduleAutoSave() {
    setSaveStatus("saving");
    state.hasPendingChanges = true;
    clearTimeout(state.saveDebounceTimer);
    state.saveDebounceTimer = setTimeout(() => {
      saveCurrentDocument();
    }, 800);
  }

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
  // Document Save Implementation
  // ----------------------------------------------------
  async function saveCurrentDocument() {
    if (!state.currentDoc || state.isSaving) return;

    // Check permission: Viewers cannot save
    if (state.currentDoc.permission === "view") {
      setSaveStatus("saved");
      state.hasPendingChanges = false;
      return;
    }

    state.isSaving = true;
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
    }
  }

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
            <div class="fw-medium">${u.name}</div>
            <div class="small ${isCurrent ? 'text-light' : 'text-muted'}">${u.email}</div>
          </div>
          ${isCurrent ? '<i class="bi bi-check-lg ms-2"></i>' : ''}
        </a>
      `;
      li.addEventListener("click", (e) => {
        e.preventDefault();
        switchUserPersona(u);
      });
      personaList.appendChild(li);
    });

    activePersonaName.textContent = state.activeUser.name;
    activePersonaBadge.textContent = state.activeUser.email.includes("alice") ? "Owner" : "Reviewer";
  }

  function switchUserPersona(user) {
    if (user.email === state.activeUser.email) return;

    state.activeUser = { email: user.email, name: user.name };
    localStorage.setItem("ajaia_active_user_email", user.email);
    localStorage.setItem("ajaia_active_user_name", user.name);

    renderPersonaDropdown();
    showToast(`Switched active persona to ${user.name}`);

    // If viewing document, refresh permissions or redirect to dashboard
    if (state.currentDoc) {
      openDocument(state.currentDoc.id);
    } else {
      loadDocuments();
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
          <p class="mb-0">${isOwnedTab ? 'No documents created yet. Click "New Document" or import a file above!' : 'No documents shared with you yet.'}</p>
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
        hour: "2-digit",
        minute: "2-digit",
      });

      const fileTypeBadge = doc.file_type === "markdown" 
        ? '<span class="badge bg-info-subtle text-info border">Markdown</span>' 
        : (doc.file_type === "plaintext" ? '<span class="badge bg-secondary-subtle text-secondary border">Text</span>' : '');

      const permissionPill = !isOwnedTab
        ? `<span class="badge ${doc.permission === 'edit' ? 'bg-success-subtle text-success' : 'bg-warning-subtle text-warning'} border">${doc.permission.toUpperCase()}</span>`
        : '';

      col.innerHTML = `
        <div class="card h-100 doc-card shadow-sm border bg-white">
          <div class="doc-icon-preview">
            <i class="bi bi-file-earmark-richtext fs-1 text-primary"></i>
          </div>
          <div class="card-body p-3 d-flex flex-column">
            <h6 class="card-title fw-bold text-dark text-truncate mb-1" title="${doc.title}">
              ${doc.title}
            </h6>
            <div class="small text-muted mb-2">
              ${isOwnedTab ? `Updated ${updatedDate}` : `Owner: ${doc.owner_name || doc.owner_email}`}
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

      col.querySelector(".doc-card").addEventListener("click", () => {
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

      // Populate UI
      docTitleInput.value = doc.title;
      quill.root.innerHTML = doc.content_html || "";
      setSaveStatus("saved");

      // Permission controls
      const isOwner = doc.permission === "owner";
      const canEdit = isOwner || doc.permission === "edit";

      permissionBadge.textContent = isOwner ? "Owner" : (doc.permission === "edit" ? "Editor" : "Viewer (Read-only)");
      permissionBadge.className = `badge ${isOwner ? 'bg-primary-subtle text-primary' : (canEdit ? 'bg-success-subtle text-success' : 'bg-warning-subtle text-warning')}`;

      // Enable/disable Quill editor
      quill.enable(canEdit);
      docTitleInput.disabled = !canEdit;

      // Metadata info
      const updatedDate = new Date(doc.updated_at).toLocaleString();
      docMetaInfo.textContent = `Owner: ${doc.owner_name} (${doc.owner_email}) • Last updated: ${updatedDate}`;

      // Download original file button
      if (doc.minio_object_key) {
        btnDownloadRaw.classList.remove("d-none");
        btnDownloadRaw.classList.add("d-flex");
      } else {
        btnDownloadRaw.classList.add("d-none");
        btnDownloadRaw.classList.remove("d-flex");
      }

      // Delete button: Only owner
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

      // Switch views
      dashboardView.classList.add("d-none");
      editorView.classList.remove("d-none");
      navDocControls.classList.remove("d-none");

      window.scrollTo(0, 0);
    } catch (err) {
      showToast(`Cannot open document: ${err.message}`, true);
      showDashboard();
    }
  }

  function showDashboard() {
    state.currentDoc = null;
    editorView.classList.add("d-none");
    navDocControls.classList.add("d-none");
    btnOpenShare.classList.add("d-none");
    btnOpenShare.classList.remove("d-flex");
    dashboardView.classList.remove("d-none");
    loadDocuments();
  }

  // ----------------------------------------------------
  // Document Actions (Create, Delete, Raw Download)
  // ----------------------------------------------------
  btnCreateDoc.addEventListener("click", async () => {
    try {
      btnCreateDoc.disabled = true;
      const newDoc = await apiFetch("/api/v1/documents", {
        method: "POST",
        body: JSON.stringify({
          title: "Untitled Document",
          content_html: "<p><br></p>",
        }),
      });
      openDocument(newDoc.id);
      showToast("New blank document created");
    } catch (err) {
      showToast(`Error creating document: ${err.message}`, true);
    } finally {
      btnCreateDoc.disabled = false;
    }
  });

  btnDeleteDoc.addEventListener("click", async () => {
    if (!state.currentDoc) return;
    if (!confirm(`Are you sure you want to permanently delete "${state.currentDoc.title}"?`)) return;

    try {
      await apiFetch(`/api/v1/documents/${state.currentDoc.id}`, { method: "DELETE" });
      showToast("Document deleted successfully");
      showDashboard();
    } catch (err) {
      showToast(`Error deleting document: ${err.message}`, true);
    }
  });

  btnDownloadRaw.addEventListener("click", () => {
    if (!state.currentDoc || !state.currentDoc.minio_object_key) return;
    // Download via direct link with auth header simulation or GET route
    window.open(`/api/v1/documents/${state.currentDoc.id}/raw?x_user_email=${encodeURIComponent(state.activeUser.email)}`, "_blank");
  });

  btnBackToDashboard.addEventListener("click", showDashboard);
  brandLink.addEventListener("click", (e) => {
    e.preventDefault();
    showDashboard();
  });

  // ----------------------------------------------------
  // Sharing Modal Implementation
  // ----------------------------------------------------
  btnOpenShare.addEventListener("click", renderShareModal);

  function renderShareModal() {
    if (!state.currentDoc) return;
    shareModalDocTitle.textContent = state.currentDoc.title;
    shareEmailInput.value = "";

    shareAccessList.innerHTML = `
      <div class="list-group-item d-flex justify-content-between align-items-center py-2">
        <div>
          <span class="fw-semibold">${state.currentDoc.owner_name}</span>
          <span class="text-muted small">(${state.currentDoc.owner_email})</span>
        </div>
        <span class="badge bg-primary">Owner</span>
      </div>
    `;

    if (state.currentDoc.shares && state.currentDoc.shares.length > 0) {
      state.currentDoc.shares.forEach((share) => {
        const item = document.createElement("div");
        item.className = "list-group-item d-flex justify-content-between align-items-center py-2";
        item.innerHTML = `
          <div>
            <span class="fw-semibold">${share.user_name || share.user_email}</span>
            <span class="text-muted small">(${share.user_email})</span>
            <span class="badge bg-secondary-subtle text-secondary ms-2">${share.permission.toUpperCase()}</span>
          </div>
          <button class="btn btn-sm btn-outline-danger py-0 px-2 btn-revoke" data-user-id="${share.user_id}">
            <i class="bi bi-x"></i> Revoke
          </button>
        `;

        item.querySelector(".btn-revoke").addEventListener("click", async () => {
          try {
            await apiFetch(`/api/v1/documents/${state.currentDoc.id}/share/${share.user_id}`, {
              method: "DELETE",
            });
            showToast(`Revoked access for ${share.user_email}`);
            // Refresh document state
            const refreshed = await apiFetch(`/api/v1/documents/${state.currentDoc.id}`);
            state.currentDoc = refreshed;
            renderShareModal();
          } catch (err) {
            showToast(`Error revoking access: ${err.message}`, true);
          }
        });

        shareAccessList.appendChild(item);
      });
    }
  }

  quickPickBob.addEventListener("click", (e) => {
    e.preventDefault();
    shareEmailInput.value = "bob@ajaia.test";
  });
  quickPickAlice.addEventListener("click", (e) => {
    e.preventDefault();
    shareEmailInput.value = "alice@ajaia.test";
  });

  shareForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!state.currentDoc) return;

    const email = shareEmailInput.value.trim();
    const permission = sharePermissionSelect.value;
    if (!email) return;

    try {
      await apiFetch(`/api/v1/documents/${state.currentDoc.id}/share`, {
        method: "POST",
        body: JSON.stringify({ email, permission }),
      });

      showToast(`Shared "${state.currentDoc.title}" with ${email} as ${permission}`);
      const refreshed = await apiFetch(`/api/v1/documents/${state.currentDoc.id}`);
      state.currentDoc = refreshed;
      renderShareModal();
    } catch (err) {
      showToast(`Failed to share: ${err.message}`, true);
    }
  });

  // ----------------------------------------------------
  // File Upload Ingestion (MinIO S3 + Parser)
  // ----------------------------------------------------
  async function handleFileUpload(file) {
    if (!file) return;

    const ext = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();
    if (ext !== ".md" && ext !== ".txt") {
      showToast("Unsupported file type. Please upload a .md or .txt file.", true);
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    uploadProgress.classList.remove("d-none");
    btnSubmitUpload.disabled = true;

    try {
      const createdDoc = await apiFetch("/api/v1/documents/upload", {
        method: "POST",
        body: formData,
      });

      uploadModal.hide();
      modalFileInput.value = "";
      showToast(`Imported "${createdDoc.title}" successfully into MinIO and Document Editor!`);
      openDocument(createdDoc.id);
    } catch (err) {
      showToast(`Import failed: ${err.message}`, true);
    } finally {
      uploadProgress.classList.add("d-none");
      btnSubmitUpload.disabled = false;
    }
  }

  btnSubmitUpload.addEventListener("click", () => {
    const file = modalFileInput.files[0];
    if (!file) {
      alert("Please select a file to upload.");
      return;
    }
    handleFileUpload(file);
  });

  // Drag and drop quick upload
  quickDropzone.addEventListener("click", () => dragFileInput.click());
  dragFileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleFileUpload(e.target.files[0]);
    }
  });

  quickDropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    quickDropzone.classList.add("dragover");
  });

  quickDropzone.addEventListener("dragleave", () => {
    quickDropzone.classList.remove("dragover");
  });

  quickDropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    quickDropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  });

  // ----------------------------------------------------
  // Initial Boot
  // ----------------------------------------------------
  loadUserPersonas();
  loadDocuments();
});
