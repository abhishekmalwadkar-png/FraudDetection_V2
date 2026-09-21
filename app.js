/**
 * Dummy Bank Portal - Fraud Operations Portal
 * Interactive Frontend Client with Live PostgreSQL Integration
 */

// State
let allTickets = [];
let filteredTickets = [];
let solvedTickets = [];
let filteredSolvedTickets = [];
let allCustomers = [];
let currentDossierTicket = null;
let knownTicketIds = new Set(JSON.parse(sessionStorage.getItem("known_ticket_ids") || "[]"));
let liveNotifications = [];
let selectedTicketIds = new Set();

// Pagination State (10 complaints per page)
let ticketCurrentPage = 1;
const ticketPageSize = 10;
let solvedCurrentPage = 1;
const solvedPageSize = 10;

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initClock();
  initEventListeners();
  checkSystemHealth();
  loadSavedNotifications();
  loadAllData();

  // 1.5-second ultra-fast real-time auto-sync with AutomationEdge Process Studio & incoming API calls
  setInterval(() => {
    const isModalOpen = document.getElementById("newTicketModal")?.classList.contains("open");
    const isDrawerOpen = document.getElementById("drawerOverlay")?.classList.contains("open");
    if (!isModalOpen && !isDrawerOpen) {
      loadOverviewStats();
      loadFraudTickets(true);
      checkSystemHealth();
    }
  }, 1500);
});

// System Health Heartbeat Monitor
async function checkSystemHealth() {
  const badge = document.getElementById("headerHealthBadge");
  const text = document.getElementById("healthStatusText");
  if (!badge || !text) return;

  try {
    const t0 = performance.now();
    const res = await fetch("/health");
    const roundtripMs = Math.round(performance.now() - t0);
    const data = await res.json();

    if (res.ok && data.status === "UP") {
      badge.className = "header-health-badge";
      text.textContent = `Live (${data.database.ping_latency_ms || roundtripMs}ms)`;
      badge.title = `Server: ${data.server} | DB: ${data.database.status} (${data.database.pool.database}) | Threads: ${data.worker_threads}`;
    } else {
      badge.className = "header-health-badge degraded";
      text.textContent = `Degraded (${roundtripMs}ms)`;
      badge.title = "Database or service connection degraded";
    }
  } catch (err) {
    badge.className = "header-health-badge down";
    text.textContent = "Offline";
    badge.title = "Backend server unreachable";
  }
}

// 1. Tab Navigation
window.switchTab = function(targetTabId) {
  const tabs = document.querySelectorAll(".nav-tab");
  tabs.forEach(t => {
    if (t.getAttribute("data-tab") === targetTabId) {
      t.classList.add("active");
    } else {
      t.classList.remove("active");
    }
  });

  document.querySelectorAll(".tab-panel").forEach(panel => {
    if (panel.id === targetTabId) {
      panel.classList.add("active");
    } else {
      panel.classList.remove("active");
    }
  });

  if (targetTabId === "tab-dashboard") loadAnalytics();
  if (targetTabId === "tab-customers") loadCustomers();
  if (targetTabId === "tab-transactions") loadTransactions();
  if (targetTabId === "tab-audit") {
    applySolvedFilters();
    loadAuditLogs();
  }
  if (targetTabId === "tab-pgadmin") loadDbStatus();
  if (targetTabId === "tab-home") renderHomeUrgentList();
};

function initTabs() {
  const tabs = document.querySelectorAll(".nav-tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const targetTabId = tab.getAttribute("data-tab");
      switchTab(targetTabId);
    });
  });
}

// 2. Real-time UTC Clock
function initClock() {
  const clockEl = document.getElementById("clockValue");
  function update() {
    const now = new Date();
    clockEl.textContent = now.toUTCString().replace("GMT", "UTC");
  }
  update();
  setInterval(update, 1000);
}

// 3. Event Listeners
function initEventListeners() {
  // Search & Filter listeners
  const searchInput = document.getElementById("ticketSearchInput");
  const filterSeverity = document.getElementById("filterSeverity");
  const filterStatus = document.getElementById("filterStatus");
  const filterIncidentType = document.getElementById("filterIncidentType");

  const onTicketFilterChange = () => {
    ticketCurrentPage = 1;
    applyFilters();
  };

  searchInput.addEventListener("input", onTicketFilterChange);
  filterSeverity.addEventListener("change", onTicketFilterChange);
  filterStatus.addEventListener("change", onTicketFilterChange);
  filterIncidentType.addEventListener("change", onTicketFilterChange);

  // Customer search
  const custSearchInput = document.getElementById("custSearchInput");
  if (custSearchInput) {
    custSearchInput.addEventListener("input", (e) => {
      const term = e.target.value.toLowerCase();
      const rows = document.querySelectorAll("#customersTableBody tr");
      rows.forEach(r => {
        r.style.display = r.textContent.toLowerCase().includes(term) ? "" : "none";
      });
    });
  }

  // Refresh & Export buttons
  document.getElementById("btnRefreshTickets").addEventListener("click", () => {
    loadAllData();
    showToast("Refreshed data from PostgreSQL database", "success");
  });

  document.getElementById("btnExportTicketsCSV").addEventListener("click", exportTicketsCSV);

  // Modal Open / Close
  const modal = document.getElementById("newTicketModal");
  document.getElementById("btnOpenNewTicketModal").addEventListener("click", () => {
    updatePresetPriority();
    modal.classList.add("open");
  });
  document.getElementById("btnCloseModal").addEventListener("click", () => {
    modal.classList.remove("open");
  });
  document.getElementById("btnCancelModal").addEventListener("click", () => {
    modal.classList.remove("open");
  });

  // Modal Amount Real-time Priority Preset Listener
  const formAmountInput = document.getElementById("formAmount");
  if (formAmountInput) {
    formAmountInput.addEventListener("input", updatePresetPriority);
    formAmountInput.addEventListener("change", updatePresetPriority);
  }

  // Modal Form Submit
  document.getElementById("newFraudTicketForm").addEventListener("submit", handleCreateNewTicket);

  // Drawer Close
  const drawerOverlay = document.getElementById("drawerOverlay");
  document.getElementById("btnCloseDrawer").addEventListener("click", () => {
    drawerOverlay.classList.remove("open");
  });
  drawerOverlay.addEventListener("click", (e) => {
    if (e.target === drawerOverlay) drawerOverlay.classList.remove("open");
  });

  // Drawer Emergency Actions & Staff Reassignment
  document.getElementById("btnDrawerFreeze").addEventListener("click", handleFreezeAction);
  document.getElementById("btnDrawerInvestigate").addEventListener("click", () => handleStatusUpdate("UNDER_INVESTIGATION"));
  document.getElementById("btnDrawerResolve").addEventListener("click", () => handleStatusUpdate("RESOLVED"));
  document.getElementById("btnDrawerEscalate").addEventListener("click", () => handleStatusUpdate("ESCALATED"));
  document.getElementById("btnReassignStaff")?.addEventListener("click", handleReassignStaff);

  // pgAdmin SQL Runner (if present)
  const runBtn = document.getElementById("btnRunSQLQuery");
  if (runBtn) {
    runBtn.addEventListener("click", executeSQLQuery);
    document.querySelectorAll(".quick-sql-presets button").forEach(btn => {
      btn.addEventListener("click", () => {
        const queryEl = document.getElementById("sqlQueryText");
        if (queryEl) {
          queryEl.value = btn.getAttribute("data-sql");
          executeSQLQuery();
        }
      });
    });
  }

  // PDF Export trigger
  const btnDownloadSAR = document.getElementById("btnDownloadSAR");
  if (btnDownloadSAR) {
    btnDownloadSAR.addEventListener("click", async () => {
      const origHtml = btnDownloadSAR.innerHTML;
      try {
        btnDownloadSAR.disabled = true;
        btnDownloadSAR.innerHTML = `<div class="spinner" style="width: 14px; height: 14px; border-width: 2px;"></div> Generating PDF...`;
        showToast("Generating Official Fraud Audit & Compliance PDF...", "info");

        const res = await fetch("/api/reports/audit-pdf");
        if (!res.ok) {
          throw new Error(`Server returned HTTP ${res.status}`);
        }

        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `Official_Fraud_Audit_Report_${new Date().toISOString().slice(0, 10)}.pdf`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(url);

        showToast("Official Audit PDF downloaded successfully.", "success");
      } catch (err) {
        showToast("Error generating PDF: " + err.message, "error");
      } finally {
        btnDownloadSAR.disabled = false;
        btnDownloadSAR.innerHTML = origHtml;
      }
    });
  }

  // Live Notification Bell Center
  const bellBtn = document.getElementById("btnNotificationBell");
  const notifDropdown = document.getElementById("notifDropdown");
  const clearNotifsBtn = document.getElementById("btnClearNotifs");

  if (bellBtn && notifDropdown) {
    bellBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const willOpen = !notifDropdown.classList.contains("open");
      if (willOpen) {
        notifDropdown.classList.add("open");
        notifDropdown.style.display = "flex";
      } else {
        notifDropdown.classList.remove("open");
        notifDropdown.style.display = "none";
      }
    });

    document.addEventListener("click", (e) => {
      if (!e.target.closest("#notifWrapper")) {
        notifDropdown.classList.remove("open");
        notifDropdown.style.display = "none";
      }
    });
  }

  if (clearNotifsBtn) {
    clearNotifsBtn.addEventListener("click", () => {
      markAllNotifsRead();
    });
  }

  const purgeNotifsBtn = document.getElementById("btnPurgeNotifs");
  if (purgeNotifsBtn) {
    purgeNotifsBtn.addEventListener("click", () => {
      clearAllNotifs();
    });
  }

  // Bulk Selection & Quick Actions Toolbar Listeners
  const selectAllCheckbox = document.getElementById("selectAllTicketsCheckbox");
  if (selectAllCheckbox) {
    selectAllCheckbox.addEventListener("change", (e) => {
      const isChecked = e.target.checked;
      const startIndex = (ticketCurrentPage - 1) * ticketPageSize;
      const paginatedTickets = filteredTickets.slice(startIndex, startIndex + ticketPageSize);
      if (isChecked) {
        paginatedTickets.forEach(t => selectedTicketIds.add(String(t.ticket_id)));
      } else {
        paginatedTickets.forEach(t => selectedTicketIds.delete(String(t.ticket_id)));
      }
      updateBulkToolbar();
      renderFraudTicketsTable(filteredTickets);
    });
  }

  const tableBody = document.getElementById("fraudTicketsTableBody");
  if (tableBody) {
    tableBody.addEventListener("change", (e) => {
      if (e.target.classList.contains("ticket-select-checkbox")) {
        const tid = String(e.target.getAttribute("data-ticket-id"));
        if (e.target.checked) {
          selectedTicketIds.add(tid);
        } else {
          selectedTicketIds.delete(tid);
        }
        updateBulkToolbar();
      }
    });
  }

  // Bulk Action Buttons
  document.getElementById("btnBulkInvestigate")?.addEventListener("click", () => executeBulkAction("UNDER_INVESTIGATION", "Bulk set to In Progress"));
  document.getElementById("btnBulkFreeze")?.addEventListener("click", () => executeBulkAction("FROZEN", "Emergency account lock applied via bulk operations"));
  document.getElementById("btnBulkResolve")?.addEventListener("click", () => executeBulkAction("RESOLVED", "Bulk resolved and closed"));
  document.getElementById("btnBulkEscalate")?.addEventListener("click", () => executeBulkAction("ESCALATED", "Bulk escalated to Senior Team"));
  document.getElementById("btnBulkAssignStaff")?.addEventListener("click", () => {
    const staff = document.getElementById("bulkStaffSelect")?.value || "Shreya Deshmukh (Support Lead)";
    executeBulkStaffAssign(staff);
  });
  document.getElementById("btnBulkExport")?.addEventListener("click", exportSelectedTicketsCSV);
  document.getElementById("btnBulkDeselect")?.addEventListener("click", clearSelectedTickets);

  // Solved Archive Search & Filter Listeners
  const solvedSearchInput = document.getElementById("solvedSearchInput");
  const filterSolvedType = document.getElementById("filterSolvedIncidentType");
  const onSolvedFilterChange = () => {
    solvedCurrentPage = 1;
    applySolvedFilters();
  };
  if (solvedSearchInput) solvedSearchInput.addEventListener("input", onSolvedFilterChange);
  if (filterSolvedType) filterSolvedType.addEventListener("change", onSolvedFilterChange);
  document.getElementById("btnExportSolvedCSV")?.addEventListener("click", exportSolvedCSV);

  // Home Action Buttons
  document.getElementById("btnHomeNewComplaint")?.addEventListener("click", () => {
    document.getElementById("newTicketModal")?.classList.add("open");
  });
  document.getElementById("btnHomeViewQueue")?.addEventListener("click", () => {
    switchTab("tab-fraud-tickets");
  });
  document.getElementById("btnHomeViewSummary")?.addEventListener("click", () => {
    switchTab("tab-dashboard");
  });

  // History Sub-Tabs Switching (Solved Archive vs Staff Activity Logs)
  document.querySelectorAll(".history-sub-tab").forEach(tabBtn => {
    tabBtn.addEventListener("click", () => {
      document.querySelectorAll(".history-sub-tab").forEach(b => b.classList.remove("active"));
      tabBtn.classList.add("active");

      const targetSubPanelId = tabBtn.getAttribute("data-subtab");
      document.querySelectorAll(".history-sub-panel").forEach(p => {
        p.classList.remove("active");
        p.style.display = "none";
      });

      const targetPanel = document.getElementById(targetSubPanelId);
      if (targetPanel) {
        targetPanel.classList.add("active");
        targetPanel.style.display = "flex";
      }

      if (targetSubPanelId === "subtab-audit-logs") {
        loadAuditLogs();
      } else {
        applySolvedFilters();
      }
    });
  });
}

// 4. Data Loading Pipeline
async function loadAllData() {
  await Promise.all([
    loadOverviewStats(),
    loadFraudTickets()
  ]);
}

async function loadOverviewStats() {
  try {
    const res = await fetch("/api/overview");
    const data = await res.json();

    const totalTickets = data.total_tickets || 0;
    const resolvedCases = data.resolved_cases || 0;
    const activeTickets = data.active_tickets !== undefined ? data.active_tickets : Math.max(0, totalTickets - resolvedCases);
    const inProgressTickets = data.under_investigation || 0;

    if (document.getElementById("kpiTotalCustomers")) document.getElementById("kpiTotalCustomers").textContent = data.total_customers || "0";
    if (document.getElementById("kpiTotalTickets")) document.getElementById("kpiTotalTickets").textContent = totalTickets;
    if (document.getElementById("badgeTicketCount")) document.getElementById("badgeTicketCount").textContent = totalTickets;
    if (document.getElementById("kpiTotalAmount")) document.getElementById("kpiTotalAmount").textContent = formatCurrency(data.total_amount || 0);
    if (document.getElementById("kpiRecoveredAmount")) document.getElementById("kpiRecoveredAmount").textContent = formatCurrency(data.recovered_amount || 0);
    if (document.getElementById("kpiFrozenAccounts")) document.getElementById("kpiFrozenAccounts").textContent = data.frozen_accounts || "0";
    if (document.getElementById("kpiCriticalCount")) document.getElementById("kpiCriticalCount").textContent = data.critical_customers || "0";

    // Active & In Progress ticket counts
    if (document.getElementById("kpiActiveTickets")) document.getElementById("kpiActiveTickets").textContent = activeTickets;
    if (document.getElementById("kpiInProgressTickets")) document.getElementById("kpiInProgressTickets").textContent = inProgressTickets;
    if (document.getElementById("bubbleActiveTickets")) document.getElementById("bubbleActiveTickets").textContent = activeTickets;
    if (document.getElementById("bubbleInProgressTickets")) document.getElementById("bubbleInProgressTickets").textContent = inProgressTickets;

    // Home Pulse Cards
    if (document.getElementById("homeActiveTickets")) document.getElementById("homeActiveTickets").textContent = activeTickets;
    if (document.getElementById("homeInProgressTickets")) document.getElementById("homeInProgressTickets").textContent = inProgressTickets;
    if (document.getElementById("homeRecoveredAmount")) document.getElementById("homeRecoveredAmount").textContent = formatCurrency(data.recovered_amount || 0);
    if (document.getElementById("homeSolvedTickets")) document.getElementById("homeSolvedTickets").textContent = resolvedCases;

    renderHomeUrgentList();

    // Dashboard recovery
    if (document.getElementById("recGrossVal")) {
      document.getElementById("recGrossVal").textContent = formatCurrency(data.total_amount || 2185930);
      document.getElementById("recRecoveredVal").textContent = formatCurrency(data.recovered_amount || 1621430);
      const pending = (data.total_amount || 2185930) - (data.recovered_amount || 1621430);
      document.getElementById("recPendingVal").textContent = formatCurrency(pending);
      const pct = Math.round(((data.recovered_amount || 1) / (data.total_amount || 1)) * 100);
      document.getElementById("recoveryRatePercent").textContent = `${pct}%`;
    }
  } catch (err) {
    console.error("Error loading overview stats:", err);
  }
}

function generateSummaryVisualizerHtml() {
  const total = allTickets.length || 1;
  const solvedCount = allTickets.filter(t => t.status === 'RESOLVED').length;
  const inProgCount = allTickets.filter(t => t.status === 'UNDER_INVESTIGATION').length;
  const frozenCount = allTickets.filter(t => t.status === 'FROZEN').length;
  const escalatedCount = allTickets.filter(t => t.status === 'ESCALATED').length;
  const openCount = allTickets.filter(t => !['RESOLVED', 'UNDER_INVESTIGATION', 'FROZEN', 'ESCALATED', 'CLOSED'].includes(t.status)).length;

  const statusSegments = [
    { label: "Solved / Refunded", count: solvedCount, color: "#10b981" },
    { label: "In Progress", count: inProgCount, color: "#f59e0b" },
    { label: "Accounts Blocked", count: frozenCount, color: "#06b6d4" },
    { label: "Escalated", count: escalatedCount, color: "#ef4444" },
    { label: "Urgent Open", count: openCount, color: "#3b82f6" }
  ].filter(s => s.count > 0);

  // SVG Donut Slices
  const r = 52;
  const circumference = 2 * Math.PI * r;
  let offset = 0;
  let circlesHtml = '';

  if (statusSegments.length === 0) {
    circlesHtml = `<circle cx="70" cy="70" r="${r}" fill="transparent" stroke="#e2e8f0" stroke-width="20"></circle>`;
  } else {
    circlesHtml = statusSegments.map(s => {
      const pct = s.count / total;
      const dashLength = pct * circumference;
      const spaceLength = circumference - dashLength;
      const currentOffset = offset;
      offset -= dashLength;
      return `<circle cx="70" cy="70" r="${r}" fill="transparent" stroke="${s.color}" stroke-width="20" stroke-dasharray="${dashLength} ${spaceLength}" stroke-dashoffset="${currentOffset}"></circle>`;
    }).join("");
  }

  return `
    <div class="home-summary-graphics-wrap">
      <div class="donut-chart-box">
        <div class="donut-svg-wrapper">
          <svg class="donut-svg" width="130" height="130" viewBox="0 0 140 140">
            ${circlesHtml}
          </svg>
          <div class="donut-center-text">
            <span class="donut-center-count">${allTickets.length}</span>
            <span class="donut-center-label">CASES</span>
          </div>
        </div>
        <div class="donut-legend-list">
          ${statusSegments.map(s => {
            const pct = Math.round((s.count / total) * 100);
            return `
              <div class="donut-legend-item">
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span class="legend-dot" style="background: ${s.color};"></span>
                  <span class="legend-label">${s.label}</span>
                </div>
                <strong class="legend-val">${s.count} <small style="color: #64748b; font-weight: normal; margin-left: 6px;">(${pct}%)</small></strong>
              </div>
            `;
          }).join("")}
        </div>
      </div>
    </div>
  `;
}

function renderHomeUrgentList() {
  const container = document.getElementById("homeUrgentList");
  if (!container) return;

  // Statuses where staff action has ALREADY been taken:
  // Frozen/Blocked, Under Investigation, Escalated, Resolved, Closed, Rejected
  const actionTakenStatuses = new Set([
    'FROZEN',
    'BLOCKED',
    'UNDER_INVESTIGATION',
    'ESCALATED',
    'RESOLVED',
    'CLOSED',
    'REJECTED'
  ]);

  // Urgent Action Required list ONLY shows fresh/open complaints needing immediate action
  const urgentTickets = allTickets.filter(t => {
    const st = String(t.status || 'OPEN').trim().toUpperCase();
    const needsAction = !actionTakenStatuses.has(st);
    const isUrgent = t.severity === 'CRITICAL' || t.severity === 'HIGH';
    return needsAction && isUrgent;
  });

  if (urgentTickets.length === 0) {
    container.innerHTML = `
      <div class="home-resolved-banner">
        <i class="fa-solid fa-circle-check"></i>
        <div>
          <strong>All Urgent Complaints Addressed & Processed</strong>
          <p>Zero critical escalations pending immediate triage. Live breakdown below:</p>
        </div>
      </div>
      ${generateSummaryVisualizerHtml()}
    `;
    return;
  }

  const displayTickets = urgentTickets.slice(0, 5);

  const urgentHtml = `
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
      <span style="font-size: 13px; font-weight: 700; color: #dc2626; display: flex; align-items: center; gap: 6px;">
        <i class="fa-solid fa-triangle-exclamation"></i> Urgent Action Required (${urgentTickets.length})
      </span>
      <button class="btn btn-xs btn-outline" onclick="switchTab('tab-fraud-tickets')">View All in Queue</button>
    </div>
    ${displayTickets.map(t => `
      <div class="critical-item" onclick="openIncidentDossier('${t.ticket_id}')">
        <div class="crit-left">
          <div class="crit-title-row">
            <span class="code-font" style="font-weight: 700; color: var(--primary);">${t.ticket_number}</span>
            ${getSeverityBadgeHtml(t.severity)}
            ${getStatusBadgeHtml(t.status)}
          </div>
          <div class="crit-name">${escapeHtml(t.full_name)} • <span class="code-font">${t.account_number}</span></div>
          <div class="crit-desc">${escapeHtml(t.incident_type)} (${formatCurrency(t.amount_involved)})</div>
        </div>
        <div class="crit-right">
          <button class="btn btn-xs btn-outline" onclick="event.stopPropagation(); openIncidentDossier('${t.ticket_id}')">
            <i class="fa-solid fa-bolt"></i> Investigate
          </button>
        </div>
      </div>
    `).join("")}
  `;

  container.innerHTML = `
    ${urgentHtml}
    ${generateSummaryVisualizerHtml()}
  `;
}

async function loadFraudTickets(isBackground = false) {
  const tbody = document.getElementById("fraudTicketsTableBody");
  try {
    const res = await fetch("/api/fraud-tickets");
    const freshTickets = await res.json();
    if (!Array.isArray(freshTickets)) return;

    if (knownTicketIds.size === 0) {
      // First visit: register existing ticket numbers & seed recent 5 as read alerts
      freshTickets.forEach(t => knownTicketIds.add(String(t.ticket_number || t.ticket_id)));
      try {
        sessionStorage.setItem("known_ticket_ids", JSON.stringify(Array.from(knownTicketIds)));
      } catch (e) {}

      if (liveNotifications.length === 0 && freshTickets.length > 0) {
        liveNotifications = freshTickets.slice(0, 5).map(t => ({
          id: t.ticket_id,
          ticket_number: t.ticket_number,
          full_name: t.full_name,
          amount: t.amount_involved,
          incident_type: t.incident_type,
          channel: t.reported_channel,
          time: t.incident_date ? new Date(t.incident_date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : "Recent",
          read: true
        }));
        saveNotifications();
        renderNotificationList();
      }

      allTickets = freshTickets;
    } else {
      // Detect newly created complaints dispatched from AutomationEdge or API
      const newArrivals = freshTickets.filter(t => !knownTicketIds.has(String(t.ticket_number || t.ticket_id)));
      
      if (newArrivals.length > 0) {
        newArrivals.forEach(t => {
          knownTicketIds.add(String(t.ticket_number || t.ticket_id));
          t.isNew = true;

          // Push into Live Notification Center
          const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
          liveNotifications.unshift({
            id: t.ticket_id,
            ticket_number: t.ticket_number,
            full_name: t.full_name,
            amount: t.amount_involved,
            incident_type: t.incident_type,
            channel: t.reported_channel,
            time: nowStr,
            read: false
          });

          showToast(`⚡ New Complaint Raised: ${t.ticket_number} (${t.full_name} - ${formatCurrency(t.amount_involved)})`, "success");
        });

        try {
          sessionStorage.setItem("known_ticket_ids", JSON.stringify(Array.from(knownTicketIds)));
        } catch (e) {}

        saveNotifications();
        triggerBellNotification(true);
        renderNotificationList();
        loadOverviewStats();
      }
      allTickets = freshTickets;
    }

    applyFilters();
  } catch (err) {
    if (!isBackground) {
      tbody.innerHTML = `<tr><td colspan="10" class="loading-state" style="color: var(--rose);">Failed to load tickets from database. Please verify backend is running.</td></tr>`;
    }
  }
}

function saveNotifications() {
  try {
    sessionStorage.setItem("bank_portal_notifs", JSON.stringify(liveNotifications.slice(0, 40)));
  } catch (e) {}
}

function loadSavedNotifications() {
  try {
    const saved = sessionStorage.getItem("bank_portal_notifs");
    if (saved) {
      liveNotifications = JSON.parse(saved);
      triggerBellNotification(false);
      renderNotificationList();
    }
  } catch (e) {}
}

function playNotificationSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(587.33, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(880, ctx.currentTime + 0.12);
    gain.gain.setValueAtTime(0.12, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.35);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.35);
  } catch (e) {}
}

// -------------------------------------------------------------
// Live Notification Center Handlers
// -------------------------------------------------------------
function triggerBellNotification(shouldRing = false) {
  const bellBtn = document.getElementById("btnNotificationBell");
  const bellBadge = document.getElementById("bellBadge");
  if (!bellBtn || !bellBadge) return;

  const unreadCount = liveNotifications.filter(n => !n.read).length;

  if (unreadCount > 0) {
    bellBadge.textContent = unreadCount > 99 ? "99+" : unreadCount;
    bellBadge.classList.add("active");
    bellBadge.style.display = "flex";
  } else {
    bellBadge.textContent = "0";
    bellBadge.classList.remove("active");
    bellBadge.style.display = "none";
  }

  // Play gentle alert sound & trigger bell shake animation ONLY when new arrivals occur
  if (shouldRing && unreadCount > 0) {
    playNotificationSound();
    bellBtn.classList.remove("ring");
    void bellBtn.offsetWidth; // trigger reflow
    bellBtn.classList.add("ring");
    setTimeout(() => bellBtn.classList.remove("ring"), 700);
  }
}

function renderNotificationList() {
  const listEl = document.getElementById("notifList");
  if (!listEl) return;

  if (liveNotifications.length === 0) {
    listEl.innerHTML = `
      <div class="notif-empty">
        <i class="fa-regular fa-bell-slash"></i>
        <span>No active alerts. Listening for live RPA complaints...</span>
      </div>
    `;
    return;
  }

  listEl.innerHTML = liveNotifications.map((n, idx) => `
    <div class="notif-item ${n.read ? '' : 'unread'}" onclick="handleNotifClick(${idx}, '${n.id}')">
      <div class="notif-icon-col">
        <i class="fa-solid fa-triangle-exclamation"></i>
      </div>
      <div class="notif-content-col">
        <div class="notif-top-row">
          <span class="notif-ticket-tag">${n.ticket_number}</span>
          <span class="notif-time">${n.time}</span>
        </div>
        <div class="notif-title">${escapeHtml(n.full_name)} • ${formatCurrency(n.amount)}</div>
        <div class="notif-desc">${escapeHtml(n.incident_type)} (${escapeHtml(n.channel)})</div>
      </div>
    </div>
  `).join("");
}

window.handleNotifClick = function(notifIndex, ticketId) {
  if (liveNotifications[notifIndex]) {
    liveNotifications[notifIndex].read = true;
    saveNotifications();
  }
  triggerBellNotification(false);
  renderNotificationList();

  const dropdown = document.getElementById("notifDropdown");
  if (dropdown) {
    dropdown.classList.remove("open");
    dropdown.style.display = "none";
  }

  // Open the incident dossier slide-over
  if (ticketId) {
    openIncidentDossier(ticketId);
  }
};

function markAllNotifsRead() {
  liveNotifications.forEach(n => n.read = true);
  saveNotifications();
  triggerBellNotification(false);
  renderNotificationList();
  showToast("All notifications marked as read & alerts cleared", "info");
}

function clearAllNotifs() {
  liveNotifications = [];
  saveNotifications();
  triggerBellNotification(false);
  renderNotificationList();
  showToast("Notification inbox cleared", "info");
}

function applyFilters() {
  const searchTerm = document.getElementById("ticketSearchInput").value.trim().toLowerCase();
  const severityFilter = document.getElementById("filterSeverity").value;
  const statusFilter = document.getElementById("filterStatus").value;
  const typeFilter = document.getElementById("filterIncidentType").value;

  // Primary complaints list ONLY shows active/unresolved complaints
  const activeTicketsPool = allTickets.filter(t => t.status !== 'RESOLVED');

  filteredTickets = activeTicketsPool.filter(t => {
    // Search
    const searchMatch = !searchTerm ||
      t.ticket_number.toLowerCase().includes(searchTerm) ||
      t.full_name.toLowerCase().includes(searchTerm) ||
      t.email.toLowerCase().includes(searchTerm) ||
      t.account_number.toLowerCase().includes(searchTerm) ||
      t.customer_code.toLowerCase().includes(searchTerm) ||
      t.incident_type.toLowerCase().includes(searchTerm);

    // Severity
    const sevMatch = severityFilter === "ALL" || t.severity === severityFilter;

    // Status
    const statusMatch = statusFilter === "ALL" || t.status === statusFilter;

    // Type
    const typeMatch = typeFilter === "ALL" || t.incident_type.toLowerCase().includes(typeFilter.toLowerCase());

    return searchMatch && sevMatch && statusMatch && typeMatch;
  });

  // Update left menu badge to show active complaints count
  const badgeTicketCount = document.getElementById("badgeTicketCount");
  if (badgeTicketCount) badgeTicketCount.textContent = activeTicketsPool.length;

  renderFraudTicketsTable(filteredTickets);
  updatePillCounts();
  applySolvedFilters();
  renderHomeUrgentList();
}

function applySolvedFilters() {
  const searchInput = document.getElementById("solvedSearchInput");
  const searchTerm = searchInput ? searchInput.value.trim().toLowerCase() : "";
  const filterType = document.getElementById("filterSolvedIncidentType");
  const typeFilter = filterType ? filterType.value : "ALL";

  solvedTickets = allTickets.filter(t => t.status === 'RESOLVED');

  const solvedBadge = document.getElementById("solvedCountBadge");
  if (solvedBadge) solvedBadge.textContent = solvedTickets.length;

  filteredSolvedTickets = solvedTickets.filter(t => {
    const searchMatch = !searchTerm ||
      t.ticket_number.toLowerCase().includes(searchTerm) ||
      t.full_name.toLowerCase().includes(searchTerm) ||
      t.email.toLowerCase().includes(searchTerm) ||
      t.account_number.toLowerCase().includes(searchTerm) ||
      t.customer_code.toLowerCase().includes(searchTerm) ||
      t.incident_type.toLowerCase().includes(searchTerm);

    const typeMatch = typeFilter === "ALL" || t.incident_type.toLowerCase().includes(typeFilter.toLowerCase());

    return searchMatch && typeMatch;
  });

  renderSolvedTicketsTable(filteredSolvedTickets);
}

function renderSolvedTicketsTable(tickets) {
  const tbody = document.getElementById("solvedTicketsTableBody");
  if (!tbody) return;

  const countEl = document.getElementById("visibleSolvedCount");
  if (countEl) countEl.textContent = tickets.length;

  if (tickets.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" class="loading-state">No solved complaints recorded yet. When a complaint is marked as Solved, it will appear here.</td></tr>`;
    renderPaginationControls("solvedPagination", 1, 0, solvedPageSize, "changeSolvedPage");
    return;
  }

  // Slicing for pagination (10 solved complaints per page)
  const totalItems = tickets.length;
  const totalPages = Math.ceil(totalItems / solvedPageSize) || 1;
  if (solvedCurrentPage > totalPages) solvedCurrentPage = totalPages;
  if (solvedCurrentPage < 1) solvedCurrentPage = 1;

  const startIndex = (solvedCurrentPage - 1) * solvedPageSize;
  const paginatedSolvedTickets = tickets.slice(startIndex, startIndex + solvedPageSize);

  tbody.innerHTML = paginatedSolvedTickets.map(t => {
    return `
      <tr>
        <td>
          <span class="code-font" style="font-weight: 700; color: var(--primary);">${t.ticket_number}</span>
        </td>
        <td>
          <div class="customer-cell">
            <span class="customer-name">${escapeHtml(t.full_name)}</span>
            <span class="customer-sub">${escapeHtml(t.city || '')}, ${escapeHtml(t.state || '')}</span>
          </div>
        </td>
        <td>
          <div class="customer-cell">
            <span class="customer-name" style="font-size: 12px;">${escapeHtml(t.email)}</span>
            <span class="customer-sub code-font">${escapeHtml(t.customer_code)}</span>
          </div>
        </td>
        <td>
          <div class="customer-cell">
            <span class="code-font" style="color: var(--text-main); font-weight: 600;">${t.account_number}</span>
            <span class="customer-sub">${t.account_type || 'SAVINGS'}</span>
          </div>
        </td>
        <td>
          <strong style="color: var(--text-main); font-size: 13px;">${escapeHtml(t.incident_type)}</strong>
          <div style="font-size: 11px; color: var(--text-dim); margin-top: 2px;">
            <i class="fa-solid fa-satellite-dish" style="font-size: 10px;"></i> ${escapeHtml(t.reported_channel)}
          </div>
        </td>
        <td>
          <div class="amount-font highlight-amber">${formatCurrency(t.amount_involved)}</div>
        </td>
        <td>
          <div class="amount-font highlight-emerald">${formatCurrency(t.recovered_amount || t.amount_involved)}</div>
        </td>
        <td>
          <span class="tag-pill tag-resolved"><i class="fa-solid fa-circle-check"></i> SOLVED</span>
        </td>
        <td>
          <span style="font-size: 12px; color: var(--text-muted);">${escapeHtml(t.assigned_investigator ? t.assigned_investigator.split('(')[0] : 'Branch Officer')}</span>
        </td>
        <td style="text-align: right;">
          <button class="btn btn-xs btn-outline" onclick="openIncidentDossier('${t.ticket_id}')">
            <i class="fa-solid fa-eye"></i> View Details
          </button>
        </td>
      </tr>
    `;
  }).join("");

  renderPaginationControls("solvedPagination", solvedCurrentPage, totalItems, solvedPageSize, "changeSolvedPage");
}

function exportSolvedCSV() {
  if (solvedTickets.length === 0) {
    showToast("No solved complaints to export", "warning");
    return;
  }
  const headers = ["Complaint_Number", "Customer_Name", "Email", "Account_Number", "Fraud_Type", "Reported_Amount", "Recovered_Amount", "Status", "Handled_By", "Created_At"];
  const rows = solvedTickets.map(t => [
    `"${t.ticket_number}"`,
    `"${t.full_name}"`,
    `"${t.email}"`,
    `"${t.account_number}"`,
    `"${t.incident_type}"`,
    t.amount_involved,
    t.recovered_amount || 0,
    `"${t.status}"`,
    `"${t.assigned_investigator || ''}"`,
    `"${t.created_at || ''}"`
  ]);

  const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map(e => e.join(","))].join("\n");
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", `Solved_Fraud_Complaints_${new Date().toISOString().slice(0, 10)}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  showToast(`Exported ${solvedTickets.length} solved complaints to CSV`, "success");
}

function renderFraudTicketsTable(tickets) {
  const tbody = document.getElementById("fraudTicketsTableBody");
  document.getElementById("visibleTicketCount").textContent = tickets.length;

  if (tickets.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" class="loading-state">No fraud tickets match your current filters.</td></tr>`;
    renderPaginationControls("ticketsPagination", 1, 0, ticketPageSize, "changeTicketPage");
    return;
  }

  // Slicing for pagination (10 complaints per page)
  const totalItems = tickets.length;
  const totalPages = Math.ceil(totalItems / ticketPageSize) || 1;
  if (ticketCurrentPage > totalPages) ticketCurrentPage = totalPages;
  if (ticketCurrentPage < 1) ticketCurrentPage = 1;

  const startIndex = (ticketCurrentPage - 1) * ticketPageSize;
  const paginatedTickets = tickets.slice(startIndex, startIndex + ticketPageSize);

  // Synchronize master checkbox state with current page tickets
  const selectAllCheckbox = document.getElementById("selectAllTicketsCheckbox");
  if (selectAllCheckbox) {
    const visibleSelectedCount = paginatedTickets.filter(t => selectedTicketIds.has(String(t.ticket_id))).length;
    selectAllCheckbox.checked = paginatedTickets.length > 0 && visibleSelectedCount === paginatedTickets.length;
    selectAllCheckbox.indeterminate = visibleSelectedCount > 0 && visibleSelectedCount < paginatedTickets.length;
  }

  tbody.innerHTML = paginatedTickets.map(t => {
    const sevBadge = getSeverityBadgeHtml(t.severity);
    const statusBadge = getStatusBadgeHtml(t.status);
    const newClass = t.isNew ? 'new-ticket-row' : '';
    const isChecked = selectedTicketIds.has(String(t.ticket_id)) ? 'checked' : '';

    return `
      <tr class="${newClass}" style="${isChecked ? 'background-color: #eff6ff;' : ''}">
        <td style="text-align: center; width: 38px;">
          <input type="checkbox" class="ticket-select-checkbox table-checkbox" data-ticket-id="${t.ticket_id}" ${isChecked}>
        </td>
        <td>
          <span class="code-font" style="font-weight: 700; color: var(--primary);">${t.ticket_number}</span>
          ${t.isNew ? '<span class="tag-pill" style="background: var(--primary); color: #fff; font-size: 9px; font-weight: 700; margin-left: 6px; padding: 2px 6px; border-radius: 4px;">NEW</span>' : ''}
        </td>
        <td>
          <div class="customer-cell">
            <span class="customer-name">${escapeHtml(t.full_name)}</span>
            <span class="customer-sub">${escapeHtml(t.city || '')}, ${escapeHtml(t.state || '')}</span>
          </div>
        </td>
        <td>
          <div class="customer-cell">
            <span class="customer-name" style="font-size: 12px;">${escapeHtml(t.email)}</span>
            <span class="customer-sub code-font">${escapeHtml(t.customer_code)}</span>
          </div>
        </td>
        <td>
          <div class="customer-cell">
            <span class="code-font" style="color: var(--text-main); font-weight: 600;">${t.account_number}</span>
            <span class="customer-sub">${t.account_type || 'SAVINGS'}</span>
          </div>
        </td>
        <td>
          <strong style="color: var(--text-main); font-size: 13px;">${escapeHtml(t.incident_type)}</strong>
          <div style="font-size: 11px; color: var(--text-dim); margin-top: 2px;">
            <i class="fa-solid fa-satellite-dish" style="font-size: 10px;"></i> ${escapeHtml(t.reported_channel)}
          </div>
        </td>
        <td>
          <div class="amount-font ${t.amount_involved > 50000 ? 'highlight-red' : 'highlight-amber'}">
            ${formatCurrency(t.amount_involved)}
          </div>
          ${t.recovered_amount > 0 ? `<div style="font-size: 10px; color: var(--emerald);">Rec: ${formatCurrency(t.recovered_amount)}</div>` : ''}
        </td>
        <td>${sevBadge}</td>
        <td>${statusBadge}</td>
        <td>
          <span style="font-size: 12px; color: var(--text-muted);">${escapeHtml(t.assigned_investigator ? t.assigned_investigator.split('(')[0] : 'Investigator')}</span>
        </td>
        <td style="text-align: right;">
          <button class="btn btn-xs btn-outline" onclick="openIncidentDossier('${t.ticket_id}')">
            <i class="fa-solid fa-eye"></i> View Details
          </button>
        </td>
      </tr>
    `;
  }).join("");

  renderPaginationControls("ticketsPagination", ticketCurrentPage, totalItems, ticketPageSize, "changeTicketPage");
}

// -------------------------------------------------------------
// Pagination Controls Generator & Handlers
// -------------------------------------------------------------
function renderPaginationControls(containerId, currentPage, totalItems, pageSize, changePageFnName) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const totalPages = Math.ceil(totalItems / pageSize) || 1;

  if (totalItems === 0) {
    container.innerHTML = `
      <div class="pagination-info">
        <span>No matching complaints found</span>
      </div>
      <div class="pagination-nav">
        <span class="pagination-page-size-tag">10 per page</span>
      </div>
    `;
    return;
  }

  const startItem = (currentPage - 1) * pageSize + 1;
  const endItem = Math.min(currentPage * pageSize, totalItems);

  // Generate numbered page buttons
  let pagesHtml = '';
  const maxButtons = 5;
  let startPage = Math.max(1, currentPage - 2);
  let endPage = Math.min(totalPages, startPage + maxButtons - 1);
  if (endPage - startPage < maxButtons - 1) {
    startPage = Math.max(1, endPage - maxButtons + 1);
  }

  if (startPage > 1) {
    pagesHtml += `<button class="pagination-btn" onclick="${changePageFnName}(1)" title="Page 1">1</button>`;
    if (startPage > 2) {
      pagesHtml += `<span class="pagination-ellipsis">…</span>`;
    }
  }

  for (let p = startPage; p <= endPage; p++) {
    const activeClass = p === currentPage ? 'active' : '';
    pagesHtml += `<button class="pagination-btn ${activeClass}" onclick="${changePageFnName}(${p})" title="Page ${p}">${p}</button>`;
  }

  if (endPage < totalPages) {
    if (endPage < totalPages - 1) {
      pagesHtml += `<span class="pagination-ellipsis">…</span>`;
    }
    pagesHtml += `<button class="pagination-btn" onclick="${changePageFnName}(${totalPages})" title="Page ${totalPages}">${totalPages}</button>`;
  }

  const prevDisabled = currentPage <= 1 ? 'disabled' : '';
  const nextDisabled = currentPage >= totalPages ? 'disabled' : '';

  container.innerHTML = `
    <div class="pagination-info">
      <span>Showing <strong>${startItem} - ${endItem}</strong> of <strong>${totalItems}</strong> complaints</span>
      <span class="pagination-page-size-tag"><i class="fa-solid fa-list-ol"></i> 10 per page</span>
    </div>
    <div class="pagination-nav">
      <button class="pagination-btn" ${prevDisabled} onclick="${changePageFnName}(${currentPage - 1})" title="Previous Page">
        <i class="fa-solid fa-chevron-left"></i> Previous
      </button>
      ${pagesHtml}
      <button class="pagination-btn" ${nextDisabled} onclick="${changePageFnName}(${currentPage + 1})" title="Next Page">
        Next <i class="fa-solid fa-chevron-right"></i>
      </button>
    </div>
  `;
}

window.changeTicketPage = function(newPage) {
  const totalPages = Math.ceil(filteredTickets.length / ticketPageSize) || 1;
  if (newPage < 1) newPage = 1;
  if (newPage > totalPages) newPage = totalPages;
  ticketCurrentPage = newPage;
  renderFraudTicketsTable(filteredTickets);
  const tableEl = document.getElementById("fraudTicketsTable");
  if (tableEl) {
    const rect = tableEl.getBoundingClientRect();
    if (rect.top < 0) {
      tableEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }
};

window.changeSolvedPage = function(newPage) {
  const totalPages = Math.ceil(filteredSolvedTickets.length / solvedPageSize) || 1;
  if (newPage < 1) newPage = 1;
  if (newPage > totalPages) newPage = totalPages;
  solvedCurrentPage = newPage;
  renderSolvedTicketsTable(filteredSolvedTickets);
  const tableEl = document.getElementById("solvedTicketsTable");
  if (tableEl) {
    const rect = tableEl.getBoundingClientRect();
    if (rect.top < 0) {
      tableEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }
};

// -------------------------------------------------------------
// Bulk Selection Handlers
// -------------------------------------------------------------
function updateBulkToolbar() {
  const bar = document.getElementById("bulkActionsBar");
  const countEl = document.getElementById("bulkSelectedCount");
  const count = selectedTicketIds.size;

  if (countEl) countEl.textContent = count;

  if (bar) {
    if (count > 0) {
      bar.style.display = "flex";
    } else {
      bar.style.display = "none";
    }
  }

  // Update master checkbox
  const selectAllCheckbox = document.getElementById("selectAllTicketsCheckbox");
  if (selectAllCheckbox) {
    const visibleSelectedCount = filteredTickets.filter(t => selectedTicketIds.has(String(t.ticket_id))).length;
    selectAllCheckbox.checked = filteredTickets.length > 0 && visibleSelectedCount === filteredTickets.length;
    selectAllCheckbox.indeterminate = visibleSelectedCount > 0 && visibleSelectedCount < filteredTickets.length;
  }
}

function clearSelectedTickets() {
  selectedTicketIds.clear();
  updateBulkToolbar();
  renderFraudTicketsTable(filteredTickets);
}

async function executeBulkAction(newStatus, actionNote) {
  if (selectedTicketIds.size === 0) return;
  const count = selectedTicketIds.size;
  const ticketIdsToUpdate = Array.from(selectedTicketIds);
  const friendlyStatus = newStatus === 'RESOLVED' ? 'Solved / Refunded' : (newStatus === 'FROZEN' ? 'Account Blocked' : (newStatus === 'ESCALATED' ? 'Escalated' : 'In Progress'));

  // Optimistically update in-memory state
  allTickets.forEach(t => {
    if (ticketIdsToUpdate.includes(String(t.ticket_id))) {
      t.status = newStatus;
      if (newStatus === "RESOLVED") {
        t.recovered_amount = t.amount_involved;
      }
      if (newStatus === "FROZEN") {
        t.account_status = "FROZEN";
      }
    }
  });
  clearSelectedTickets();
  applyFilters();
  renderHomeUrgentList();

  try {
    const res = await fetch("/api/fraud-tickets/bulk-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticket_ids: ticketIdsToUpdate,
        status: newStatus,
        action_taken: actionNote || `Bulk action: ${friendlyStatus}`
      })
    });

    const data = await res.json();
    if (data.success) {
      showToast(`Successfully updated ${data.updated_count} complaints to "${friendlyStatus}"`, "success");
      loadAllData();
    } else {
      showToast("Bulk action failed: " + (data.error || data.detail || "Unknown error"), "error");
      loadAllData();
    }
  } catch (err) {
    showToast("Error updating complaints: " + err.message, "error");
    loadAllData();
  }
}

function exportSelectedTicketsCSV() {
  if (selectedTicketIds.size === 0) {
    showToast("Please select at least one complaint to export.", "warning");
    return;
  }

  const selectedRows = allTickets.filter(t => selectedTicketIds.has(String(t.ticket_id)));
  
  const headers = ["Complaint #", "Customer Name", "Email", "Phone", "Account #", "Type", "Fraud Type", "Amount (INR)", "Recovered (INR)", "Priority", "Status", "Reported Via", "Created At"];
  const rows = selectedRows.map(t => [
    t.ticket_number,
    `"${(t.full_name || '').replace(/"/g, '""')}"`,
    t.email || '',
    t.phone || '',
    t.account_number || '',
    t.account_type || '',
    `"${(t.incident_type || '').replace(/"/g, '""')}"`,
    t.amount_involved || 0,
    t.recovered_amount || 0,
    t.severity || '',
    t.status || '',
    `"${(t.reported_channel || '').replace(/"/g, '""')}"`,
    t.created_at || ''
  ]);

  const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map(e => e.join(","))].join("\n");
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", `Selected_Fraud_Complaints_${new Date().toISOString().slice(0, 10)}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);

  showToast(`Exported ${selectedRows.length} selected complaints to CSV file`, "success");
}

function updatePillCounts() {
  const crit = allTickets.filter(t => t.severity === "CRITICAL").length;
  const high = allTickets.filter(t => t.severity === "HIGH").length;
  const med = allTickets.filter(t => t.severity === "MEDIUM").length;
  const res = allTickets.filter(t => t.status === "RESOLVED").length;

  document.getElementById("pillCritCount").textContent = `${crit} Urgent`;
  document.getElementById("pillHighCount").textContent = `${high} High`;
  document.getElementById("pillMedCount").textContent = `${med} Medium`;
  document.getElementById("pillResCount").textContent = `${res} Solved`;
}

// 5. Incident Dossier Slide-Over
window.openIncidentDossier = async function(ticketId) {
  try {
    const res = await fetch(`/api/fraud-tickets/${ticketId}`);
    if (!res.ok) throw new Error("Ticket not found");
    const ticket = await res.json();
    currentDossierTicket = ticket;

    document.getElementById("drawerTicketNumber").textContent = ticket.ticket_number;
    
    // Severity badge in drawer
    const sevBadge = document.getElementById("drawerSeverityBadge");
    sevBadge.className = `tag-pill tag-${ticket.severity.toLowerCase()}`;
    sevBadge.textContent = ticket.severity;

    // Victim details
    document.getElementById("dossierName").textContent = ticket.full_name;
    document.getElementById("dossierCode").textContent = ticket.customer_code;
    document.getElementById("dossierEmail").textContent = ticket.email;
    document.getElementById("dossierPhone").textContent = ticket.phone;
    document.getElementById("dossierAccount").textContent = ticket.account_number;
    document.getElementById("dossierBalance").textContent = `${ticket.account_type || 'CHECKING'} (${formatCurrency(ticket.balance)}) - ${ticket.account_status}`;

    // Forensics
    document.getElementById("dossierType").textContent = ticket.incident_type;
    document.getElementById("dossierAmount").textContent = formatCurrency(ticket.amount_involved);
    document.getElementById("dossierRecovered").textContent = formatCurrency(ticket.recovered_amount);
    document.getElementById("dossierChannel").textContent = ticket.reported_channel;
    document.getElementById("dossierIp").textContent = ticket.flagged_ip_or_location || "N/A";
    document.getElementById("dossierSuspect").textContent = ticket.suspect_entity || "Under Forensics Tracing";
    document.getElementById("dossierDescription").textContent = ticket.description;
    document.getElementById("dossierAction").textContent = ticket.action_taken || "Incident registered in database. Active forensics docket.";

    // Assigned Staff
    const currentStaff = ticket.assigned_investigator || "Shreya Deshmukh (Support Lead)";
    const dossierStaffEl = document.getElementById("dossierInvestigator");
    if (dossierStaffEl) dossierStaffEl.textContent = currentStaff;
    const selectStaffEl = document.getElementById("selectDrawerStaff");
    if (selectStaffEl) selectStaffEl.value = currentStaff;

    // Linked Transactions
    const txnListEl = document.getElementById("drawerTxnList");
    if (ticket.transactions && ticket.transactions.length > 0) {
      txnListEl.innerHTML = ticket.transactions.map(tx => `
        <div class="drawer-txn-item">
          <div style="display: flex; justify-content: space-between;">
            <strong class="code-font highlight-cyan">${tx.txn_reference}</strong>
            <span class="amount-font highlight-red">${formatCurrency(tx.amount)}</span>
          </div>
          <div style="font-size: 11px; color: var(--text-dim); margin-top: 3px;">
            Target: ${escapeHtml(tx.merchant_or_recipient)} • Score: <strong>${tx.fraud_risk_score}/100</strong> • Status: <strong>${tx.status}</strong>
          </div>
        </div>
      `).join("");
    } else {
      txnListEl.innerHTML = `<div style="font-size: 12px; color: var(--text-dim);">No transactions flagged.</div>`;
    }

    // Audit logs
    const auditListEl = document.getElementById("drawerAuditList");
    if (ticket.audit_logs && ticket.audit_logs.length > 0) {
      auditListEl.innerHTML = ticket.audit_logs.map(log => `
        <div class="drawer-audit-item">
          <div style="display: flex; justify-content: space-between; font-size: 11px;">
            <strong>${escapeHtml(log.actor)}</strong>
            <span style="color: var(--text-dim);">${formatDate(log.created_at)}</span>
          </div>
          <div style="font-size: 11px; color: var(--text-muted); margin-top: 3px;">${escapeHtml(log.details)}</div>
        </div>
      `).join("");
    } else {
      auditListEl.innerHTML = `<div style="font-size: 12px; color: var(--text-dim);">No prior audit history.</div>`;
    }

    document.getElementById("drawerOverlay").classList.add("open");
  } catch (err) {
    showToast("Error opening ticket dossier: " + err.message, "error");
  }
};

// 6. Actions in Drawer
async function handleFreezeAction() {
  if (!currentDossierTicket) return;
  const accNum = currentDossierTicket.account_number;
  const ticketNum = currentDossierTicket.ticket_number;
  const ticketId = currentDossierTicket.ticket_id;

  // Optimistically update in-memory state right away
  currentDossierTicket.status = "FROZEN";
  currentDossierTicket.account_status = "FROZEN";
  allTickets.forEach(t => {
    if (String(t.ticket_id) === String(ticketId) || t.ticket_number === ticketNum) {
      t.status = "FROZEN";
      t.account_status = "FROZEN";
    }
  });
  applyFilters();
  renderHomeUrgentList();
  document.getElementById("drawerOverlay").classList.remove("open");

  try {
    const res = await fetch("/api/freeze-account", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_number: accNum, ticket_number: ticketNum })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Account ${accNum} has been temporarily blocked to protect customer funds.`, "warning");
      loadAllData();
    }
  } catch (err) {
    showToast("Could not block account: " + err.message, "error");
    loadAllData();
  }
}

async function handleStatusUpdate(newStatus) {
  if (!currentDossierTicket) return;
  const ticketId = currentDossierTicket.ticket_id;
  const ticketNum = currentDossierTicket.ticket_number;

  // Optimistically update in-memory state right away
  currentDossierTicket.status = newStatus;
  allTickets.forEach(t => {
    if (String(t.ticket_id) === String(ticketId) || t.ticket_number === ticketNum) {
      t.status = newStatus;
      if (newStatus === "RESOLVED") {
        t.recovered_amount = t.amount_involved;
      }
      if (newStatus === "FROZEN") {
        t.account_status = "FROZEN";
      }
    }
  });
  applyFilters();
  renderHomeUrgentList();
  document.getElementById("drawerOverlay").classList.remove("open");

  try {
    const res = await fetch(`/api/fraud-tickets/${ticketId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: newStatus,
        action_taken: `Staff updated status to ${newStatus} on ${new Date().toLocaleDateString()}`
      })
    });
    const data = await res.json();
    if (data.success) {
      const friendlyStatus = newStatus === 'RESOLVED' ? 'Solved / Refunded' : (newStatus === 'FROZEN' ? 'Account Blocked' : (newStatus === 'ESCALATED' ? 'Escalated' : 'In Progress'));
      showToast(`Complaint ${currentDossierTicket.ticket_number} updated to "${friendlyStatus}"`, "success");
      loadAllData();
    }
  } catch (err) {
    showToast("Could not update status: " + err.message, "error");
    loadAllData();
  }
}

// 7. Create New Fraud Ticket Form with Preset Priority
function getPriorityForAmount(amt) {
  const num = parseFloat(amt) || 0;
  if (num >= 100000) {
    return {
      level: "CRITICAL",
      label: "Urgent Priority (₹1,00,000+)",
      tagClass: "tag-critical",
      icon: "fa-triangle-exclamation"
    };
  }
  if (num >= 50000) {
    return {
      level: "HIGH",
      label: "High Priority (₹50,000 - ₹1,00,000)",
      tagClass: "tag-high",
      icon: "fa-circle-exclamation"
    };
  }
  if (num >= 10000) {
    return {
      level: "MEDIUM",
      label: "Medium Priority (₹10,000 - ₹50,000)",
      tagClass: "tag-medium",
      icon: "fa-shield-halved"
    };
  }
  return {
    level: "LOW",
    label: "Normal Priority (< ₹10,000)",
    tagClass: "tag-low",
    icon: "fa-circle-info"
  };
}

function updatePresetPriority() {
  const amountInput = document.getElementById("formAmount");
  const badgeEl = document.getElementById("formSeverityBadge");
  const hiddenInput = document.getElementById("formSeverity");
  if (!amountInput || !badgeEl || !hiddenInput) return;

  const priorityInfo = getPriorityForAmount(amountInput.value);
  hiddenInput.value = priorityInfo.level;
  badgeEl.className = `tag-pill ${priorityInfo.tagClass}`;
  badgeEl.innerHTML = `<i class="fa-solid ${priorityInfo.icon}"></i> ${priorityInfo.label}`;
}

async function handleReassignStaff() {
  if (!currentDossierTicket) return;
  const newStaff = document.getElementById("selectDrawerStaff").value;
  const ticketId = currentDossierTicket.ticket_id;
  const ticketNum = currentDossierTicket.ticket_number;

  // Optimistically update in-memory state
  currentDossierTicket.assigned_investigator = newStaff;
  const match = allTickets.find(t => String(t.ticket_id) === String(ticketId) || t.ticket_number === ticketNum);
  if (match) match.assigned_investigator = newStaff;
  
  const dossierStaffEl = document.getElementById("dossierInvestigator");
  if (dossierStaffEl) dossierStaffEl.textContent = newStaff;

  applyFilters();

  try {
    const res = await fetch(`/api/fraud-tickets/${ticketId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        assigned_investigator: newStaff,
        action_taken: `Staff reassigned complaint to ${newStaff}`
      })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Complaint ${ticketNum} reassigned to ${newStaff}`, "success");
      loadAllData();
    }
  } catch (err) {
    showToast("Error reassigning staff: " + err.message, "error");
  }
}

async function executeBulkStaffAssign(newStaff) {
  if (selectedTicketIds.size === 0) {
    showToast("Please select at least one complaint to assign staff.", "warning");
    return;
  }

  const ticketIdsToUpdate = Array.from(selectedTicketIds);

  // Optimistically update in-memory state
  allTickets.forEach(t => {
    if (ticketIdsToUpdate.includes(String(t.ticket_id))) {
      t.assigned_investigator = newStaff;
    }
  });
  clearSelectedTickets();
  applyFilters();

  try {
    const res = await fetch("/api/fraud-tickets/bulk-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticket_ids: ticketIdsToUpdate,
        assigned_investigator: newStaff,
        action_taken: `Bulk assigned complaints to ${newStaff}`
      })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Successfully assigned ${data.updated_count} complaints to ${newStaff}`, "success");
      loadAllData();
    } else {
      showToast("Bulk staff assignment failed: " + (data.error || data.detail || "Unknown error"), "error");
      loadAllData();
    }
  } catch (err) {
    showToast("Error updating staff: " + err.message, "error");
    loadAllData();
  }
}

async function handleCreateNewTicket(e) {
  e.preventDefault();
  const amt = parseFloat(document.getElementById("formAmount").value) || 0;
  const computedSeverity = getPriorityForAmount(amt).level;
  const staffAssignee = document.getElementById("formStaffAssignee") ? document.getElementById("formStaffAssignee").value : "Shreya Deshmukh (Support Lead)";

  const payload = {
    full_name: document.getElementById("formCustName").value,
    email: document.getElementById("formCustEmail").value,
    phone: document.getElementById("formCustPhone").value,
    account_number: document.getElementById("formAccNum").value,
    account_type: document.getElementById("formAccType").value,
    incident_type: document.getElementById("formIncidentType").value,
    amount_involved: amt,
    severity: computedSeverity,
    assigned_investigator: staffAssignee,
    suspect_entity: document.getElementById("formSuspect").value,
    description: document.getElementById("formDescription").value,
    reported_channel: "Customer Help Desk"
  };

  try {
    const res = await fetch("/api/fraud-tickets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Fraud Complaint ${data.ticket_number} registered & assigned to ${staffAssignee}!`, "success");
      document.getElementById("newTicketModal").classList.remove("open");
      document.getElementById("newFraudTicketForm").reset();
      updatePresetPriority();
      loadAllData();
    }
  } catch (err) {
    showToast("Error registering complaint: " + err.message, "error");
  }
}

// 8. Customer 360 Directory
async function loadCustomers() {
  const tbody = document.getElementById("customersTableBody");
  try {
    const res = await fetch("/api/customers");
    allCustomers = await res.json();

    tbody.innerHTML = allCustomers.map(c => `
      <tr>
        <td><span class="code-font highlight-cyan">${c.customer_code}</span></td>
        <td>
          <div class="customer-cell">
            <span class="customer-name">${escapeHtml(c.full_name)}</span>
            <span class="customer-sub">${escapeHtml(c.phone || '')}</span>
          </div>
        </td>
        <td><span style="font-size: 12px; color: var(--text-muted);">${escapeHtml(c.email)}</span></td>
        <td><span style="font-size: 12px;">${escapeHtml(c.city || 'N/A')}, ${escapeHtml(c.state || '')}</span></td>
        <td><span class="code-font" style="color: #fff;">${c.account_number || 'ACT-PENDING'}</span></td>
        <td><span class="tag-pill tag-cyan">${c.account_type || 'CHECKING'}</span></td>
        <td><span class="amount-font highlight-emerald">${formatCurrency(c.balance)}</span></td>
        <td>
          <span class="tag-pill ${c.account_status === 'FROZEN' ? 'tag-frozen' : 'tag-resolved'}">
            ${c.account_status || 'ACTIVE'}
          </span>
        </td>
        <td>${getSeverityBadgeHtml(c.risk_tier || 'LOW')}</td>
        <td>
          <span class="tag-pill ${c.fraud_reports_count > 0 ? 'tag-critical' : 'tag-low'}">
            ${c.fraud_reports_count} Incident${c.fraud_reports_count === 1 ? '' : 's'}
          </span>
        </td>
        <td style="text-align: right;">
          <button class="btn btn-xs btn-outline" onclick="filterByCustomerName('${escapeHtml(c.full_name)}')">
            <i class="fa-solid fa-list-check"></i> View Fraud
          </button>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="11" class="loading-state">Error loading customer directory.</td></tr>`;
  }
}

window.filterByCustomerName = function(name) {
  const navFraud = document.getElementById("navTabFraudTickets");
  if (navFraud) navFraud.click();
  document.getElementById("ticketSearchInput").value = name;
  applyFilters();
};

// 9. Live Transactions
async function loadTransactions() {
  const tbody = document.getElementById("txnsTableBody");
  try {
    const res = await fetch("/api/transactions");
    const txns = await res.json();

    tbody.innerHTML = txns.map(tx => `
      <tr>
        <td><span class="code-font highlight-cyan">${tx.txn_reference}</span></td>
        <td>
          <div class="customer-cell">
            <span class="customer-name">${escapeHtml(tx.full_name)}</span>
            <span class="customer-sub code-font">${tx.account_number}</span>
          </div>
        </td>
        <td><span class="code-font" style="color: #fff;">${tx.account_number}</span></td>
        <td><span class="amount-font highlight-red">${formatCurrency(tx.amount)}</span></td>
        <td><span class="tag-pill tag-cyan">${tx.txn_type}</span></td>
        <td><span style="font-size: 12px;">${escapeHtml(tx.merchant_or_recipient)}</span></td>
        <td><span class="code-font" style="font-size: 11px; color: var(--text-dim);">${escapeHtml(tx.ip_address || 'Internal')}</span></td>
        <td>
          <div style="display: flex; align-items: center; gap: 8px;">
            <div class="progress-bar-wrap" style="width: 60px;">
              <div class="bar-fill ${tx.fraud_risk_score > 75 ? 'red' : 'amber'}" style="width: ${tx.fraud_risk_score}%;"></div>
            </div>
            <strong class="code-font ${tx.fraud_risk_score > 75 ? 'highlight-red' : 'highlight-amber'}">${tx.fraud_risk_score}%</strong>
          </div>
        </td>
        <td>
          <span class="tag-pill ${tx.is_fraud_flagged ? 'tag-critical' : 'tag-resolved'}">
            ${tx.is_fraud_flagged ? 'FLAGGED' : 'CLEAN'}
          </span>
        </td>
        <td>
          <span class="tag-pill ${tx.status === 'BLOCKED' ? 'tag-frozen' : (tx.status === 'HELD' ? 'tag-high' : 'tag-resolved')}">
            ${tx.status}
          </span>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="10" class="loading-state">Error loading transactions.</td></tr>`;
  }
}

// 10. Threat Analytics / Executive Charts
async function loadAnalytics() {
  try {
    const res = await fetch("/api/analytics");
    const data = await res.json();

    // Incident types bar chart
    const chartTypesEl = document.getElementById("chartIncidentTypes");
    if (chartTypesEl && data.by_type) {
      const maxCount = Math.max(...data.by_type.map(d => d.count), 1);
      chartTypesEl.innerHTML = data.by_type.map(item => {
        const pct = Math.round((item.count / maxCount) * 100);
        return `
          <div class="chart-row">
            <div class="chart-label-group">
              <span>${escapeHtml(item.type)}</span>
              <strong>${item.count} cases (${formatCurrency(item.amount)})</strong>
            </div>
            <div class="chart-bar-bg">
              <div class="chart-bar-fill" style="width: ${pct}%; background: linear-gradient(90deg, #2563eb, #38bdf8);"></div>
            </div>
          </div>
        `;
      }).join("");
    }

    // Reporting channels
    const channelsEl = document.getElementById("chartChannels");
    if (channelsEl && data.by_channel) {
      channelsEl.innerHTML = data.by_channel.map(ch => `
        <div class="channel-card">
          <div class="channel-icon"><i class="fa-solid fa-tower-broadcast"></i></div>
          <div>
            <strong style="font-size: 13px; color: #fff;">${escapeHtml(ch.channel)}</strong>
            <div style="font-size: 11px; color: var(--text-dim); margin-top: 2px;">
              ${ch.count} reports • ${formatCurrency(ch.amount)}
            </div>
          </div>
        </div>
      `).join("");
    }

    // Critical queue list
    const critQueueEl = document.getElementById("criticalQueueList");
    if (critQueueEl) {
      const critTickets = allTickets.filter(t => t.severity === "CRITICAL" || t.status === "FROZEN").slice(0, 4);
      critQueueEl.innerHTML = critTickets.map(ct => `
        <div class="queue-item" onclick="openIncidentDossier('${ct.ticket_id}')">
          <div>
            <strong style="font-size: 13px; color: #fff;">${escapeHtml(ct.full_name)} (${ct.ticket_number})</strong>
            <div style="font-size: 11px; color: var(--text-dim);">${escapeHtml(ct.incident_type)}</div>
          </div>
          <div style="text-align: right;">
            <div class="amount-font highlight-red">${formatCurrency(ct.amount_involved)}</div>
            <span class="tag-pill tag-critical" style="font-size: 9px; padding: 2px 6px;">${ct.status}</span>
          </div>
        </div>
      `).join("");
    }
  } catch (err) {
    console.error("Error loading analytics:", err);
  }
}

// 11. Audit Logs
async function loadAuditLogs() {
  const tbody = document.getElementById("auditTableBody");
  try {
    const res = await fetch("/api/audit-logs");
    const logs = await res.json();

    tbody.innerHTML = logs.map(l => `
      <tr>
        <td><span class="code-font" style="color: var(--text-dim);">#LOG-${l.log_id}</span></td>
        <td><span class="code-font highlight-cyan">${l.ticket_number || 'SYSTEM'}</span></td>
        <td><strong style="color: #fff; font-size: 12px;">${escapeHtml(l.actor)}</strong></td>
        <td><span class="tag-pill tag-high">${escapeHtml(l.action)}</span></td>
        <td><span style="font-size: 12px; color: var(--text-muted);">${escapeHtml(l.details)}</span></td>
        <td><span class="code-font" style="font-size: 11px; color: var(--text-dim);">${escapeHtml(l.ip_address || '10.0.0.1')}</span></td>
        <td><span style="font-size: 11px; color: var(--text-dim);">${formatDate(l.created_at)}</span></td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="loading-state">Error loading audit logs.</td></tr>`;
  }
}

// 12. PostgreSQL & pgAdmin Hub
async function loadDbStatus() {
  try {
    const res = await fetch("/api/db-status");
    const db = await res.json();
    const dbBadge = document.getElementById("dbNameBadge");
    if (dbBadge) dbBadge.textContent = db.database;
  } catch (err) {
    console.error("Error loading db status:", err);
  }
}

async function executeSQLQuery() {
  const query = document.getElementById("sqlQueryText").value.trim();
  const resultsContainer = document.getElementById("sqlResultsContainer");
  const countBadge = document.getElementById("sqlRowCountBadge");
  const statusEl = document.getElementById("sqlExecutionStatus");

  if (!query) {
    showToast("Please enter an SQL query to execute", "warning");
    return;
  }

  resultsContainer.innerHTML = `<div class="loading-state"><div class="spinner"></div> Executing SQL query against PostgreSQL...</div>`;

  try {
    const res = await fetch("/api/execute-sql", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query })
    });
    const data = await res.json();

    if (!res.ok || data.error) {
      statusEl.textContent = "Error";
      statusEl.className = "highlight-rose";
      resultsContainer.innerHTML = `<div style="padding: 20px; color: var(--rose); font-family: var(--font-mono); font-size: 12px;">PostgreSQL Error: ${escapeHtml(data.error)}</div>`;
      countBadge.textContent = "0 rows";
      return;
    }

    statusEl.textContent = "Query executed successfully";
    statusEl.className = "highlight-emerald";
    countBadge.textContent = `${data.row_count || 0} rows`;

    if (data.columns && data.rows) {
      let tableHtml = `<table class="data-table"><thead><tr>`;
      data.columns.forEach(col => {
        tableHtml += `<th>${escapeHtml(col)}</th>`;
      });
      tableHtml += `</tr></thead><tbody>`;

      data.rows.forEach(row => {
        tableHtml += `<tr>`;
        row.forEach(cell => {
          tableHtml += `<td class="code-font" style="font-size: 12px;">${cell !== null ? escapeHtml(String(cell)) : '<span style="color: var(--text-dim)">NULL</span>'}</td>`;
        });
        tableHtml += `</tr>`;
      });
      tableHtml += `</tbody></table>`;
      resultsContainer.innerHTML = tableHtml;
    } else {
      resultsContainer.innerHTML = `<div style="padding: 20px; color: var(--emerald);">${escapeHtml(data.message || 'Done')}</div>`;
    }
  } catch (err) {
    resultsContainer.innerHTML = `<div style="padding: 20px; color: var(--rose);">Execution failed: ${err.message}</div>`;
  }
}

// 13. CSV Export
function exportTicketsCSV() {
  if (allTickets.length === 0) {
    showToast("No ticket data to export", "warning");
    return;
  }

  const headers = ["Ticket Number", "Customer Name", "Customer Code", "Email", "Phone", "Account Number", "Incident Type", "Amount Flagged", "Recovered Amount", "Severity", "Status", "Investigator", "Date"];
  const rows = allTickets.map(t => [
    `"${t.ticket_number}"`,
    `"${t.full_name}"`,
    `"${t.customer_code}"`,
    `"${t.email}"`,
    `"${t.phone}"`,
    `"${t.account_number}"`,
    `"${t.incident_type}"`,
    t.amount_involved,
    t.recovered_amount,
    `"${t.severity}"`,
    `"${t.status}"`,
    `"${t.assigned_investigator}"`,
    `"${t.incident_date}"`
  ]);

  const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map(e => e.join(","))].join("\n");
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", `dummy_bank_fraud_report_${new Date().toISOString().slice(0, 10)}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  showToast("CSV export completed successfully", "success");
}

// Utility Helpers
function getSeverityBadgeHtml(sev) {
  const s = (sev || "MEDIUM").toUpperCase();
  if (s === "CRITICAL") return `<span class="tag-pill tag-critical"><i class="fa-solid fa-triangle-exclamation"></i> Urgent</span>`;
  if (s === "HIGH") return `<span class="tag-pill tag-high"><i class="fa-solid fa-circle-exclamation"></i> High</span>`;
  if (s === "MEDIUM") return `<span class="tag-pill tag-medium">Medium</span>`;
  return `<span class="tag-pill tag-low">Normal</span>`;
}

function getStatusBadgeHtml(status) {
  const s = (status || "OPEN").toUpperCase();
  if (s === "RESOLVED") return `<span class="tag-pill tag-resolved"><i class="fa-solid fa-circle-check"></i> Solved</span>`;
  if (s === "FROZEN") return `<span class="tag-pill tag-frozen"><i class="fa-solid fa-lock"></i> Blocked</span>`;
  if (s === "ESCALATED") return `<span class="tag-pill tag-critical"><i class="fa-solid fa-user-shield"></i> Escalated</span>`;
  if (s === "UNDER_INVESTIGATION") return `<span class="tag-pill tag-investigating"><i class="fa-solid fa-clock"></i> In Progress</span>`;
  if (s === "OPEN" || s === "NEW") return `<span class="tag-pill tag-open"><i class="fa-solid fa-bolt"></i> Urgent Open</span>`;
  return `<span class="tag-pill tag-investigating"><i class="fa-solid fa-clock"></i> ${escapeHtml(status)}</span>`;
}

function formatCurrency(val) {
  const num = typeof val === "number" ? val : parseFloat(val || 0);
  return "₹" + num.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatDate(isoStr) {
  if (!isoStr) return "--";
  try {
    const d = new Date(isoStr);
    return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return isoStr;
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <i class="fa-solid ${type === 'error' ? 'fa-circle-xmark' : (type === 'warning' ? 'fa-triangle-exclamation' : 'fa-circle-check')}"></i>
    <span>${escapeHtml(message)}</span>
  `;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}
