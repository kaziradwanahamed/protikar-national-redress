"""Custom DRF RBAC permission classes scoped by Doptor Seat, Role Level & Oversight Cell."""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from apps.accounts.models import User
from apps.organogram.models import DoptorSeat, RoleLevel


class IsVerifiedCitizen(BasePermission):
    """Allows access only to authenticated citizens with a verified CitizenProfile."""

    message = "Verified citizen identity (myGov/Porichoy/OTP) is required."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.account_type == User.AccountType.CITIZEN):
            return False
        profile = getattr(user, "citizen_profile", None)
        return bool(profile and profile.identity_verified)


class IsDoptorOfficer(BasePermission):
    """Allows access only to authenticated Government Officers with an active Doptor seat."""

    message = "Active Doptor Government Official session is required."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.account_type in (User.AccountType.OFFICER, User.AccountType.ARBITRATOR)
            and bool(user.doptor_seat_id)
        )


class HasDoptorSeatRole(BasePermission):
    """
    Role-level RBAC gate reading `allowed_role_levels` from the view.
    Example on view: `allowed_role_levels = (RoleLevel.GRO, RoleLevel.APPELLATE)`
    """

    message = "Your current Doptor seat role level does not permit this action."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        allowed = getattr(view, "allowed_role_levels", None)
        if not allowed:
            return bool(user.doptor_role_level)
        return user.doptor_role_level in allowed


class IsAssignedSeatOrSupervisor(BasePermission):
    """
    Object-level RBAC check for Complaints or TicketAssignments:
    Permits access if the officer's current `doptor_seat_id` holds an active assignment
    on the ticket OR is a supervisory ancestor seat in the Doptor organogram.
    """

    message = "Access restricted to the assigned Doptor seat or its supervisory hierarchy."

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser or user.is_oversight_cell:
            return True
        if not user.doptor_seat_id:
            return False

        complaint = getattr(obj, "complaint", obj)
        active_seat_ids = set(
            complaint.assignments.filter(is_active=True).values_list("doptor_seat_id", flat=True)
        )
        if user.doptor_seat_id in active_seat_ids:
            return True

        # Walk upward from each assigned seat to check if viewer is an ancestor supervisor/Appellate
        for seat_id in active_seat_ids:
            cursor = DoptorSeat.objects.select_related("parent_seat").filter(
                doptor_seat_id=seat_id
            ).first()
            visited = set()
            while cursor and cursor.parent_seat and cursor.doptor_seat_id not in visited:
                visited.add(cursor.doptor_seat_id)
                cursor = cursor.parent_seat
                if cursor.doptor_seat_id == user.doptor_seat_id:
                    return True
        return False


class IsOversightCellMember(BasePermission):
    """Strict RBAC gate for Cabinet Oversight Cell operations (e.g. whistleblower unsealing)."""

    message = "Action restricted strictly to authorized Oversight Cell personnel."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_oversight_cell)


class CanFilePriorityComplaint(BasePermission):
    """Blocks priority routing when a citizen has >= 3 verified false-filing strikes."""

    message = "Account is under mandatory manual pre-moderation due to prior false filings."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        profile = getattr(user, "citizen_profile", None)
        if not profile:
            return False
        return bool(profile.priority_routing_eligible and not profile.requires_manual_premoderation)


class IsGROOrOversight(BasePermission):
    """Permits GRO, Appellate officers, or Oversight Cell members."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return bool(
            user.is_oversight_cell
            or user.doptor_role_level in (RoleLevel.GRO, RoleLevel.APPELLATE)
            or user.is_superuser
        )
