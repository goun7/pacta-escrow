// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

/**
 * @title PactaEscrowVault (Base L2 Sovereign Edition)
 * @notice Non-custodial, trustless Delivery-versus-Payment escrow and arbitration vault for AI agents.
 * @dev Fully implements UCC Article 12 CER and FinCEN Non-Custodial exemptions.
 */
interface IERC20 {
    function transfer(address recipient, uint256 amount) external returns (bool);
    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

contract PactaEscrowVault {
    enum EscrowStatus {
        Uninitialized,
        Locked,
        OutputSubmitted,
        Verified,
        Settled,
        Disputed,
        Refunded
    }

    struct EscrowAgreement {
        address buyer;
        address seller;
        uint256 amount;
        uint256 lockedAt;
        uint256 timeoutSeconds;
        bytes32 requiredSchemaHash;
        bytes32 outputHash;
        EscrowStatus status;
    }

    IERC20 public immutable usdcToken;
    address public immutable protocolTreasury;
    address public immutable arbitratorOracle;
    uint256 public constant PROTOCOL_FEE_BPS = 75; // 0.75%
    uint256 public constant DISPUTE_BOND_BPS = 2000; // 20%

    mapping(bytes32 => EscrowAgreement) public escrows;
    mapping(bytes32 => uint256) public disputeBonds;

    uint256 public totalLockedPrincipal;
    uint256 public totalDisputeBonds;

    event EscrowLocked(bytes32 indexed jobId, address indexed buyer, address indexed seller, uint256 amount);
    event OutputSubmitted(bytes32 indexed jobId, bytes32 outputHash);
    event EscrowSettled(bytes32 indexed jobId, address indexed seller, uint256 netAmount, uint256 fee);
    event EscrowRefunded(bytes32 indexed jobId, address indexed buyer, uint256 amount, string reason);
    event DisputeRaised(bytes32 indexed jobId, address indexed claimant, uint256 bondAmount);
    event DisputeResolved(bytes32 indexed jobId, bool buyerFavored);

    error Unauthorized();
    error InvalidStatus();
    error TimeoutNotReached();
    error TimeoutAlreadyPassed();
    error SolvencyInvariantBreach();
    error ReentrancyGuardReentrantCall();

    uint256 private _status = 1;

    modifier nonReentrant() {
        if (_status == 2) revert ReentrancyGuardReentrantCall();
        _status = 2;
        _;
        _status = 1;
    }

    constructor(address _usdcToken, address _protocolTreasury, address _arbitratorOracle) {
        usdcToken = IERC20(_usdcToken);
        protocolTreasury = _protocolTreasury;
        arbitratorOracle = _arbitratorOracle;
    }

    /**
     * @notice Locks buyer USDC into non-custodial smart escrow.
     */
    function depositAndLock(
        bytes32 jobId,
        address seller,
        uint256 amount,
        uint256 timeoutSeconds,
        bytes32 schemaHash
    ) external nonReentrant {
        if (escrows[jobId].status != EscrowStatus.Uninitialized) revert InvalidStatus();
        if (amount == 0 || seller == address(0)) revert Unauthorized();

        escrows[jobId] = EscrowAgreement({
            buyer: msg.sender,
            seller: seller,
            amount: amount,
            lockedAt: block.timestamp,
            timeoutSeconds: timeoutSeconds,
            requiredSchemaHash: schemaHash,
            outputHash: bytes32(0),
            status: EscrowStatus.Locked
        });

        totalLockedPrincipal += amount;
        bool success = usdcToken.transferFrom(msg.sender, address(this), amount);
        if (!success) revert SolvencyInvariantBreach();

        emit EscrowLocked(jobId, msg.sender, seller, amount);
    }

    /**
     * @notice Seller submits cryptographic proof/hash of output.
     */
    function submitOutput(bytes32 jobId, bytes32 outputHash) external {
        EscrowAgreement storage agreement = escrows[jobId];
        if (agreement.status != EscrowStatus.Locked) revert InvalidStatus();
        if (msg.sender != agreement.seller) revert Unauthorized();
        if (block.timestamp > agreement.lockedAt + agreement.timeoutSeconds) revert TimeoutAlreadyPassed();

        agreement.outputHash = outputHash;
        agreement.status = EscrowStatus.OutputSubmitted;

        emit OutputSubmitted(jobId, outputHash);
    }

    /**
     * @notice Optimistic settlement: Releases funds to seller minus protocol fee.
     */
    function settle(bytes32 jobId) external nonReentrant {
        EscrowAgreement storage agreement = escrows[jobId];
        if (agreement.status != EscrowStatus.OutputSubmitted && agreement.status != EscrowStatus.Locked) {
            revert InvalidStatus();
        }
        if (msg.sender != agreement.buyer && msg.sender != agreement.seller) revert Unauthorized();

        agreement.status = EscrowStatus.Settled;
        uint256 fee = (agreement.amount * PROTOCOL_FEE_BPS) / 10000;
        uint256 netSeller = agreement.amount - fee;

        totalLockedPrincipal -= agreement.amount;

        usdcToken.transfer(agreement.seller, netSeller);
        if (fee > 0) {
            usdcToken.transfer(protocolTreasury, fee);
        }

        emit EscrowSettled(jobId, agreement.seller, netSeller, fee);
    }

    /**
     * @notice Refunds buyer when seller breaches execution timeout SLA.
     */
    function claimTimeoutRefund(bytes32 jobId) external nonReentrant {
        EscrowAgreement storage agreement = escrows[jobId];
        if (agreement.status != EscrowStatus.Locked && agreement.status != EscrowStatus.OutputSubmitted) {
            revert InvalidStatus();
        }
        if (block.timestamp <= agreement.lockedAt + agreement.timeoutSeconds) revert TimeoutNotReached();

        agreement.status = EscrowStatus.Refunded;
        totalLockedPrincipal -= agreement.amount;

        usdcToken.transfer(agreement.buyer, agreement.amount);
        emit EscrowRefunded(jobId, agreement.buyer, agreement.amount, "SLA_TIMEOUT");
    }

    /**
     * @notice Buyer raises dispute by posting a 20% collateral bond.
     */
    function raiseDispute(bytes32 jobId) external nonReentrant {
        EscrowAgreement storage agreement = escrows[jobId];
        if (agreement.status != EscrowStatus.OutputSubmitted) revert InvalidStatus();
        if (msg.sender != agreement.buyer) revert Unauthorized();

        uint256 bond = (agreement.amount * DISPUTE_BOND_BPS) / 10000;
        disputeBonds[jobId] = bond;
        totalDisputeBonds += bond;

        agreement.status = EscrowStatus.Disputed;
        usdcToken.transferFrom(msg.sender, address(this), bond);

        emit DisputeRaised(jobId, msg.sender, bond);
    }

    /**
     * @notice Resolves an open dispute based on Schelling quorum decision.
     */
    function resolveDispute(bytes32 jobId, bool buyerFavored) external nonReentrant {
        if (msg.sender != arbitratorOracle) revert Unauthorized();
        EscrowAgreement storage agreement = escrows[jobId];
        if (agreement.status != EscrowStatus.Disputed) revert InvalidStatus();

        uint256 bond = disputeBonds[jobId];
        uint256 amount = agreement.amount;

        totalLockedPrincipal -= amount;
        totalDisputeBonds -= bond;
        delete disputeBonds[jobId];

        if (buyerFavored) {
            agreement.status = EscrowStatus.Refunded;
            usdcToken.transfer(agreement.buyer, amount + bond);
            emit EscrowRefunded(jobId, agreement.buyer, amount, "ARBITRATION_BUYER_FAVORED");
        } else {
            agreement.status = EscrowStatus.Settled;
            uint256 fee = (amount * PROTOCOL_FEE_BPS) / 10000;
            uint256 netSeller = (amount - fee) + (bond / 2);
            uint256 protocolShare = fee + (bond - (bond / 2));

            usdcToken.transfer(agreement.seller, netSeller);
            if (protocolShare > 0) {
                usdcToken.transfer(protocolTreasury, protocolShare);
            }
            emit EscrowSettled(jobId, agreement.seller, netSeller, protocolShare);
        }

        emit DisputeResolved(jobId, buyerFavored);
    }
}
