"""
Test-only confirmation channels.

Never imported by production CLI/authorization paths. Synthetic echo providers
require ``JOBOPS_ALLOW_TEST_CONFIRMATION=1`` + privilege when passed into
``InteractiveApprovalGate`` (see ``resolve_confirmation_channel``).
"""
from __future__ import annotations

from approval_controller import ConfirmationPrompt


class EchoChallengeChannel:
    """
    Test-only channel that correctly echoes the challenge.

    Still goes through InteractiveApprovalGate MAC + ledger binding — it does
    not bypass confirmation verification, only supplies the interactive response.
    """

    def present_and_confirm(self, prompt: ConfirmationPrompt) -> str:
        return prompt.challenge


class FabricatedConfirmationChannel:
    """Adversarial channel that returns a fabricated (wrong) confirmation."""

    def __init__(self, response: str = "fabricated-confirmation") -> None:
        self.response = response

    def present_and_confirm(self, prompt: ConfirmationPrompt) -> str:
        return self.response


class ProgrammaticEchoChannel:
    """
    Adversarial stand-in that programmatically echoes the challenge.

    Used by negative tests to prove production authorization rejects channel
    substitution without authenticated test configuration.
    """

    def present_and_confirm(self, prompt: ConfirmationPrompt) -> str:
        return prompt.challenge
