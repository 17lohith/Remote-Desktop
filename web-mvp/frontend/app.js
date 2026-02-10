// ---------------------------------------------------------------
// Remote Desktop – Web MVP Frontend
//
// Change API_BASE when deploying:
//   Local  : http://127.0.0.1:8000
//   Prod   : https://your-api-domain.com
// ---------------------------------------------------------------

const API_BASE = "http://127.0.0.1:8000";

// ---- Health check on page load --------------------------------

async function checkHealth() {
    const dot = document.getElementById("status-dot");
    const text = document.getElementById("status-text");

    try {
        const res = await fetch(`${API_BASE}/api/health`);
        const data = await res.json();
        dot.classList.add("ok");
        text.textContent = `Backend OK | Relay: ${data.relay_url} | Sessions: ${data.active_sessions}`;
    } catch (e) {
        dot.classList.remove("ok");
        text.textContent = "Backend unreachable – is uvicorn running on port 8000?";
    }
}

window.addEventListener("load", checkHealth);

// ---- Create Session -------------------------------------------

let lastCreatedCode = "";

async function createSession() {
    const btn = document.getElementById("btn-create");
    const result = document.getElementById("create-result");

    btn.disabled = true;
    btn.textContent = "Creating...";

    try {
        const res = await fetch(`${API_BASE}/api/sessions`, { method: "POST" });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Failed to create session");
        }

        const data = await res.json();
        lastCreatedCode = data.code;

        document.getElementById("created-code").textContent = data.code;
        document.getElementById("created-relay").textContent = data.relay_url;
        document.getElementById("created-status").textContent = data.status;
        document.getElementById("share-cmd").textContent =
            `python share_screen.py --relay ${data.relay_url}`;

        result.className = "result success";
        btn.textContent = "Create New Session";

        checkHealth();
    } catch (e) {
        result.className = "result error";
        result.innerHTML = `<div class="value" style="color:#fca5a5">${e.message}</div>`;
    } finally {
        btn.disabled = false;
    }
}

// ---- Join Session ---------------------------------------------

async function joinSession() {
    const btn = document.getElementById("btn-join");
    const input = document.getElementById("join-code-input");
    const result = document.getElementById("join-result");
    const code = input.value.trim().toUpperCase();

    if (code.length !== 6) {
        result.className = "result error";
        result.innerHTML = `<div class="value" style="color:#fca5a5">Enter a 6-character code.</div>`;
        return;
    }

    btn.disabled = true;
    btn.textContent = "Joining...";

    try {
        const res = await fetch(`${API_BASE}/api/sessions/join`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code }),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Failed to join");
        }

        const data = await res.json();

        document.getElementById("join-status").textContent = data.status;
        document.getElementById("join-relay").textContent = data.relay_url;
        document.getElementById("view-cmd").textContent =
            `python view_screen.py --relay ${data.relay_url} --code ${data.code}`;

        result.className = "result success";
        btn.textContent = "Join Session";

        checkHealth();
    } catch (e) {
        result.className = "result error";
        result.innerHTML = `<div class="value" style="color:#fca5a5">${e.message}</div>`;
        btn.textContent = "Join Session";
    } finally {
        btn.disabled = false;
    }
}

// ---- Copy code to clipboard -----------------------------------

async function copyCode() {
    if (!lastCreatedCode) return;
    try {
        await navigator.clipboard.writeText(lastCreatedCode);
        document.getElementById("copy-hint").textContent = "Copied!";
        setTimeout(() => {
            document.getElementById("copy-hint").textContent = "Click to copy";
        }, 2000);
    } catch {
        // Fallback for non-HTTPS
        const ta = document.createElement("textarea");
        ta.value = lastCreatedCode;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        document.getElementById("copy-hint").textContent = "Copied!";
        setTimeout(() => {
            document.getElementById("copy-hint").textContent = "Click to copy";
        }, 2000);
    }
}

// ---- Auto-uppercase the code input ----------------------------

document.getElementById("join-code-input").addEventListener("input", function () {
    this.value = this.value.toUpperCase().replace(/[^A-Z0-9]/g, "");
});

// ---- Enter key triggers join ----------------------------------

document.getElementById("join-code-input").addEventListener("keydown", function (e) {
    if (e.key === "Enter") joinSession();
});
