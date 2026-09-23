/**
 * PACTA ESCROW PROTOCOL — COCKPIT LOGIC (2026.1)
 * Reactive simulation and state visualizer without external dependencies.
 */

document.addEventListener('DOMContentLoaded', () => {
  // DOM Elements
  const btnRunHappy = document.getElementById('btnRunHappy');
  const btnRunCorrupt = document.getElementById('btnRunCorrupt');
  const btnRunDispute = document.getElementById('btnRunDispute');

  const inputAmount = document.getElementById('inputAmount');
  const inputTimeout = document.getElementById('inputTimeout');
  const selectTier = document.getElementById('selectTier');

  const pulse1 = document.getElementById('pulse1');
  const pulse2 = document.getElementById('pulse2');
  const wireLabel1 = document.getElementById('wireLabel1');
  const wireLabel2 = document.getElementById('wireLabel2');

  const buyerStatus = document.getElementById('buyerStatus');
  const vaultStatus = document.getElementById('vaultStatus');
  const sellerStatus = document.getElementById('sellerStatus');

  const dispJobId = document.getElementById('dispJobId');
  const dispAmount = document.getElementById('dispAmount');
  const dispFee = document.getElementById('dispFee');
  const dispPayout = document.getElementById('dispPayout');
  const dispBadge = document.getElementById('dispBadge');
  const dispTx = document.getElementById('dispTx');
  const consoleOutput = document.getElementById('consoleOutput');
  const toastContainer = document.getElementById('toastContainer');

  // Schema Playground Elements
  const schemaInput = document.getElementById('schemaInput');
  const btnValidatePayload = document.getElementById('btnValidatePayload');
  const schemaResultBox = document.getElementById('schemaResultBox');

  // Quorum Simulator Elements
  const sliderBuyerVotes = document.getElementById('sliderBuyerVotes');
  const labelBuyerVotes = document.getElementById('labelBuyerVotes');
  const inputDisputeBond = document.getElementById('inputDisputeBond');
  const arbitratorTableBody = document.getElementById('arbitratorTableBody');

  // Tab Navigation
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabPanes = document.querySelectorAll('.tab-pane');

  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      tabPanes.forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      const target = document.getElementById(btn.dataset.tab);
      if (target) target.classList.add('active');
    });
  });

  // Dynamic Amount Recalculator
  function updateInspectorPreview() {
    const amt = parseFloat(inputAmount.value) || 10.0;
    const fee = (amt * 0.0075).toFixed(6);
    const payout = (amt - fee).toFixed(6);
    dispAmount.textContent = `${amt.toFixed(6)} USDC`;
    dispFee.textContent = `${fee} USDC (0.75%)`;
    dispPayout.textContent = `${payout} USDC`;
  }
  inputAmount.addEventListener('input', updateInspectorPreview);

  // Helper: Toast Notifications
  function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  // Helper: Console Log
  function logConsole(msg) {
    const time = new Date().toISOString().substring(11, 19);
    consoleOutput.textContent += `[${time}] ${msg}\n`;
    consoleOutput.scrollTop = consoleOutput.scrollHeight;
  }

  function clearConsole() {
    consoleOutput.textContent = '';
  }

  // Helper: Lock buttons during animation
  function setSimulating(isSimulating) {
    btnRunHappy.disabled = isSimulating;
    btnRunCorrupt.disabled = isSimulating;
    btnRunDispute.disabled = isSimulating;
  }

  // SCENARIO 1: Happy Path
  btnRunHappy.addEventListener('click', async () => {
    setSimulating(true);
    try {
      clearConsole();
      logConsole("INITIALIZING M2M ATOMIC DvP TRANSACTION...");

      const amt = parseFloat(inputAmount.value) || 10.0;
      const timeout = parseInt(inputTimeout.value) || 5000;
      const tier = selectTier.value;
      const fee = (amt * 0.0075).toFixed(6);
      const payout = (amt - fee).toFixed(6);

      const jobId = "job-" + Math.random().toString(36).substring(2, 9);
      dispJobId.textContent = jobId;
      dispAmount.textContent = `${amt.toFixed(6)} USDC`;
      dispFee.textContent = `${fee} USDC (0.75%)`;
      dispPayout.textContent = `${payout} USDC`;
      dispBadge.textContent = "ESCROW_LOCKED";
      dispBadge.className = "badge";
      dispTx.textContent = "Awaiting Settlement...";

      // Step 1: Request
      wireLabel1.textContent = "HTTP GET /v1/alpha";
      pulse1.className = "wire-pulse active-forward";
      buyerStatus.textContent = "Querying Seller API...";
      logConsole(`[x402] Buyer Agent calls Seller: GET /v1/alpha`);

      await new Promise(r => setTimeout(r, 600));

      // Step 2: 402 Challenge
      pulse1.className = "wire-pulse";
      wireLabel2.textContent = `HTTP 402 (Price: ${amt} USDC)`;
      pulse2.className = "wire-pulse active-backward";
      sellerStatus.textContent = "Challenging with x402...";
      logConsole(`[x402] Seller responds: 402 Payment Required (Price: ${amt} USDC, Escrow Vault: 0xPacta...)`);

      await new Promise(r => setTimeout(r, 600));

      // Step 3: Vault Lock
      pulse2.className = "wire-pulse";
      wireLabel1.textContent = `depositAndLock(${amt} USDC)`;
      pulse1.className = "wire-pulse active-forward";
      vaultStatus.textContent = `ESCROW_LOCKED (${amt} USDC)`;
      logConsole(`[Vault] Buyer deposits ${amt} USDC into non-custodial smart escrow contract.`);

      await new Promise(r => setTimeout(r, 700));

      // Step 4: Execution & Proof
      pulse1.className = "wire-pulse";
      wireLabel2.textContent = "Tamga WASI Receipt (4,520 ops)";
      pulse2.className = "wire-pulse active-backward";
      sellerStatus.textContent = "Output & Receipt Delivered";
      logConsole(`[Tamga] Seller executes task in WASI sandbox. Output hash: 0x8f1a...b2c9`);

      await new Promise(r => setTimeout(r, 600));

      // Step 5: Verification & Settle
      pulse2.className = "wire-pulse";
      vaultStatus.textContent = "State: SETTLED";
      dispBadge.textContent = "SETTLED";
      dispBadge.className = "badge badge-success";
      const settlementTxHash = "0x" + Array.from({length: 64}, () => Math.floor(Math.random()*16).toString(16)).join('');
      dispTx.textContent = settlementTxHash;

      logConsole(`[Tier-1] Status: 200 OK, Latency: 140ms < ${timeout}ms SLA, JSON-Schema PASS.`);
      if (tier === "TIER2_CRYPTOGRAPHIC") {
        logConsole(`[Tier-2] Tamga WASI instruction trace & hash verified.`);
      }
      logConsole(`[Settled] ${payout} USDC released to Seller. ${fee} USDC transferred to Protocol Treasury.`);
      showToast(`Escrow Settled: ${payout} USDC released to Seller (Tx: ${settlementTxHash.substring(0, 10)}...)`, "success");
    } finally {
      setSimulating(false);
    }
  });

  // SCENARIO 2: Corrupt Schema
  btnRunCorrupt.addEventListener('click', async () => {
    setSimulating(true);
    try {
      clearConsole();
      logConsole("INJECTING MALFORMED SELLER PAYLOAD (CORRUPTION TEST)...");

      const amt = parseFloat(inputAmount.value) || 5.0;
      const jobId = "job-" + Math.random().toString(36).substring(2, 9);
      dispJobId.textContent = jobId;
      dispAmount.textContent = `${amt.toFixed(6)} USDC`;
      dispFee.textContent = "0.000000 USDC";
      dispPayout.textContent = "0.000000 USDC";
      dispBadge.textContent = "ESCROW_LOCKED";
      dispBadge.className = "badge";
      dispTx.textContent = "None";

      wireLabel1.textContent = `depositAndLock(${amt} USDC)`;
      pulse1.className = "wire-pulse active-forward";
      logConsole(`[Vault] ${amt} USDC locked in escrow.`);

      await new Promise(r => setTimeout(r, 600));

      pulse1.className = "wire-pulse";
      wireLabel2.textContent = "Corrupted JSON Body";
      pulse2.className = "wire-pulse active-backward";
      logConsole(`[Seller] Seller returns JSON missing required 'confidence' metric.`);

      await new Promise(r => setTimeout(r, 700));

      pulse2.className = "wire-pulse";
      dispBadge.textContent = "AUTO_REFUNDED";
      dispBadge.className = "badge badge-danger";
      vaultStatus.textContent = "State: AUTO_REFUNDED";

      logConsole(`[Tier-1 Alert] Schema Invariant Violation: Missing required property 'confidence'.`);
      logConsole(`[Invariant Action] Escrow revoked immediately. 100% (${amt.toFixed(6)} USDC) refunded to Buyer Agent.`);
      showToast(`Schema Breach: ${amt} USDC automatically refunded to Buyer!`, "danger");
    } finally {
      setSimulating(false);
    }
  });

  // SCENARIO 3: Subjective Dispute & Schelling Arbitration
  btnRunDispute.addEventListener('click', async () => {
    setSimulating(true);
    try {
      clearConsole();
      logConsole("TRIGGERING SCHELLING ARBITRATION QUORUM...");

      const amt = parseFloat(inputAmount.value) || 25.0;
      const bond = (amt * 0.20).toFixed(6);

      const jobId = "job-" + Math.random().toString(36).substring(2, 9);
      dispJobId.textContent = jobId;
      dispAmount.textContent = `${amt.toFixed(6)} USDC`;
      dispFee.textContent = "0.000000 USDC";
      dispPayout.textContent = "0.000000 USDC";
      dispBadge.textContent = "ARBITRATION_IN_PROGRESS";
      dispBadge.className = "badge";
      dispTx.textContent = "Pending Quorum...";

      logConsole(`[Dispute] Buyer claims subjective fraud (hallucinated data).`);
      logConsole(`[Bond] Buyer deposits ${bond} USDC (20% anti-griefing collateral).`);
      logConsole(`[Quorum] 5 Arbitrator nodes selected via VRF committee.`);

      await new Promise(r => setTimeout(r, 800));

      logConsole(`[Voting] 4 Nodes vote FAVOR BUYER. 1 Rogue node votes FAVOR SELLER.`);
      logConsole(`[Schelling Resolution] Majority reached (80%).`);
      logConsole(`[Slashing] Rogue node 0xNodeEpsilon_Rogue slashed 50 PACTA!`);
      logConsole(`[Restitution] ${amt} USDC principal + ${bond} USDC bond returned to Buyer.`);

      dispBadge.textContent = "SLASHED_REFUNDED";
      dispBadge.className = "badge badge-danger";
      vaultStatus.textContent = "State: SLASHED_REFUNDED";
      showToast("Arbitration Resolved: Buyer Favored, Rogue Node Slashed!", "warning");
    } finally {
      setSimulating(false);
    }
  });

  // LIVE SCHEMA PLAYGROUND
  btnValidatePayload.addEventListener('click', () => {
    try {
      const parsed = JSON.parse(schemaInput.value);
      const required = ["status", "ticker", "action", "confidence"];
      const missing = required.filter(r => !(r in parsed));

      if (missing.length > 0) {
        schemaResultBox.className = "result-box fail mono";
        schemaResultBox.textContent = `[SCHEMA INVARIANT BREACH]\nError: Missing required fields: [${missing.join(', ')}]\nStatus: REJECTED (Auto-Refund Triggered)`;
        showToast("Schema Invariant Rejected!", "danger");
      } else if (typeof parsed.confidence !== 'number' || parsed.confidence < 0 || parsed.confidence > 1) {
        schemaResultBox.className = "result-box fail mono";
        schemaResultBox.textContent = `[TYPE CONSTRAINT BREACH]\nError: Field 'confidence' must be float between 0.0 and 1.0\nStatus: REJECTED`;
        showToast("Type Constraint Failed!", "danger");
      } else {
        schemaResultBox.className = "result-box pass mono";
        schemaResultBox.textContent = `[INVARIANT VERIFIED]\nStatus: HTTP 200 OK\nSchema Conformance: 100% MATCH\nFields Checked: ${required.join(', ')}\nResult: READY FOR ON-CHAIN SETTLEMENT`;
        showToast("Schema Invariant Verified!", "success");
      }
    } catch (e) {
      schemaResultBox.className = "result-box fail mono";
      schemaResultBox.textContent = `[MALFORMED JSON PARSE ERROR]\n${e.message}`;
      showToast("Invalid JSON Syntax!", "danger");
    }
  });

  // QUORUM SIMULATOR SLIDER
  function updateQuorumTable() {
    const buyerVotes = parseInt(sliderBuyerVotes.value);
    const sellerVotes = 5 - buyerVotes;
    const bond = parseFloat(inputDisputeBond.value) || 5.0;

    labelBuyerVotes.textContent = `${buyerVotes} Buyer / ${sellerVotes} Seller`;

    const nodes = [
      { id: "0xNodeAlpha_01", stake: 2000 },
      { id: "0xNodeBeta_02", stake: 1500 },
      { id: "0xNodeGamma_03", stake: 3000 },
      { id: "0xNodeDelta_04", stake: 1000 },
      { id: "0xNodeEpsilon_05", stake: 500 }
    ];

    const buyerFavored = buyerVotes >= sellerVotes;
    const rewardPool = bond * 0.5;
    const majCount = buyerFavored ? buyerVotes : sellerVotes;
    const rewardPerNode = majCount > 0 ? (rewardPool / majCount).toFixed(2) : "0.00";

    let html = "";
    nodes.forEach((node, idx) => {
      const isBuyerVote = idx < buyerVotes;
      const inMajority = (isBuyerVote === buyerFavored);

      let outcomeText = "";
      let rowClass = "";

      if (inMajority) {
        outcomeText = `<span class="text-emerald">+${rewardPerNode} USDC Reward</span>`;
      } else {
        const penalty = (node.stake * Math.pow((5 - majCount) / 5, 2) * 0.1).toFixed(1);
        outcomeText = `<span class="text-rose font-bold">-${penalty} PACTA (SLASHED)</span>`;
        rowClass = "row-slashed";
      }

      const badgeClass = isBuyerVote ? "badge-success" : "badge-danger";
      const voteText = isBuyerVote ? "FAVOR BUYER" : "FAVOR SELLER";

      html += `
        <tr class="${rowClass}">
          <td class="mono">${node.id}</td>
          <td>${node.stake.toLocaleString()} PACTA</td>
          <td><span class="badge ${badgeClass}">${voteText}</span></td>
          <td class="mono">0x${Math.random().toString(16).substring(2, 10)}...</td>
          <td>${outcomeText}</td>
        </tr>
      `;
    });

    arbitratorTableBody.innerHTML = html;
  }

  sliderBuyerVotes.addEventListener('input', updateQuorumTable);
  inputDisputeBond.addEventListener('input', updateQuorumTable);

  // Initial table render
  updateQuorumTable();
});
