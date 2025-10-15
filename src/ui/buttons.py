import discord
from ..core.user_stats import find_pending_request, update_pending_request

ROLE_HIERARCHY = {
    "Trainee Member": 1,
    "2nd_years": 2,
    "3rd_years": 3,
    "4th_years": 4,
    "Core Member": 4
}


def get_user_level(user_roles):
    level = 0
    for role in user_roles:
        if role.name in ROLE_HIERARCHY:
            level = max(level, ROLE_HIERARCHY[role.name])
    return level


def can_approve_request(approver_roles, requester_roles):
    """Check if approver can approve requester's leave based on hierarchy."""
    approver_level = get_user_level(approver_roles)
    requester_level = get_user_level(requester_roles)
    return approver_level > requester_level  # Approver must have higher level than requester


def get_role_display_name(user_roles):
    """Get the display name of user's highest role"""
    highest_level = 0
    role_name = "Unknown"

    for role in user_roles:
        if role.name in ROLE_HIERARCHY:
            level = ROLE_HIERARCHY[role.name]
            if level > highest_level:
                highest_level = level
                role_name = role.name

    return role_name


class LeaveApprovalView(discord.ui.View):
    def __init__(self, request_id: str):
        super().__init__(timeout=None)
        self.request_id = request_id

    async def _close_thread(self, thread: discord.Thread, reason: str, approver_name: str):
        await thread.edit(name=f"{thread.name} - ({reason})", locked=True, archived=True)
        await thread.send(f"This thread has been closed by {approver_name}.")

    async def _check_permissions(self, interaction: discord.Interaction, requester_id: int) -> bool:
        """Enhanced permission checking with proper hierarchy"""
        # 1. Users cannot approve their own requests
        if interaction.user.id == requester_id:
            await interaction.response.send_message(
                "You cannot approve or deny your own leave request.",
                ephemeral=True
            )
            return False

        # 2. Get requester member object
        try:
            requester = await interaction.guild.fetch_member(requester_id)
        except discord.NotFound:
            await interaction.response.send_message(
                "Could not find the user who requested this leave.",
                ephemeral=True
            )
            return False

        # 3. Check hierarchy permissions
        if not can_approve_request(interaction.user.roles, requester.roles):
            approver_role = get_role_display_name(interaction.user.roles)
            requester_role = get_role_display_name(requester.roles)

            await interaction.response.send_message(
                f"Insufficient permissions.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="leave_approve_btn")
    async def approve_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Update request status first
        request_data = update_pending_request(self.request_id, "approved", interaction.user.id)
        if not request_data:
            await interaction.response.send_message(
                "This request no longer exists or has already been handled.",
                ephemeral=True
            )
            return

        # Check permissions
        if not await self._check_permissions(interaction, request_data["member_id"]):
            return

        # Get participants
        approver = interaction.user
        try:
            requester = await interaction.guild.fetch_member(request_data["member_id"])
        except discord.NotFound:
            await interaction.response.send_message("Could not find the requester.", ephemeral=True)
            return

        # Extract request details
        leave_type = request_data.get("type", "Unknown").capitalize()
        start_date = request_data["dates"]["start"]
        end_date = request_data["dates"]["end"]
        reason = request_data.get("reason", "No reason provided")
        mode = request_data.get("mode", "")

        # Create tracking message
        mode_text = f"\nMode: {mode}" if mode else ""
        leave_tracking_message = f"""```Leave on ({start_date} to {end_date})
Leave Type: {leave_type}
Reason: {reason}{mode_text}```From {requester.mention} Approved by: {approver.mention}"""

        # Update embed
        original_embed = interaction.message.embeds[0]
        original_embed.title = "Leave Request - Approved"
        original_embed.color = discord.Color.green()
        original_embed.set_footer(text=f"Approved by {approver.display_name} ({get_role_display_name(approver.roles)})")

        # Disable buttons
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=original_embed, view=self)

        # Post to tracking channel
        leave_tracking_channel_id = 1415019014224089147
        leave_tracking_channel = interaction.client.get_channel(leave_tracking_channel_id)
        if leave_tracking_channel:
            await leave_tracking_channel.send(leave_tracking_message)

        # Close thread if in one
        if isinstance(interaction.channel, discord.Thread):
            await self._close_thread(interaction.channel, "Approved", approver.display_name)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.red, custom_id="leave_deny_btn")
    async def deny_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Update request status first
        request_data = update_pending_request(self.request_id, "denied", interaction.user.id)
        if not request_data:
            await interaction.response.send_message(
                "This request no longer exists or has already been handled.",
                ephemeral=True
            )
            return

        # Check permissions
        if not await self._check_permissions(interaction, request_data["member_id"]):
            return

        # Get participants
        approver = interaction.user
        try:
            requester = await interaction.guild.fetch_member(request_data["member_id"])
        except discord.NotFound:
            await interaction.response.send_message("Could not find the requester.", ephemeral=True)
            return

        # Extract request details
        leave_type = request_data.get("type", "Unknown").capitalize()
        start_date = request_data["dates"]["start"]
        end_date = request_data["dates"]["end"]
        reason = request_data.get("reason", "No reason provided")
        mode = request_data.get("mode", "")

        # Create tracking message
        mode_text = f"\nMode: {mode}" if mode else ""
        leave_tracking_message = f"""```Leave on ({start_date} to {end_date})
Leave Type: {leave_type}
Reason: {reason}{mode_text}```From {requester.mention} Denied by: {approver.mention}"""

        # Update embed
        original_embed = interaction.message.embeds[0]
        original_embed.title = "Leave Request - Denied"
        original_embed.color = discord.Color.red()
        original_embed.set_footer(text=f"Denied by {approver.display_name} ({get_role_display_name(approver.roles)})")

        # Disable buttons
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=original_embed, view=self)

        # Post to tracking channel
        leave_tracking_channel_id = 1415019014224089147
        leave_tracking_channel = interaction.client.get_channel(leave_tracking_channel_id)
        if leave_tracking_channel:
            await leave_tracking_channel.send(leave_tracking_message)

        # Close thread if in one
        if isinstance(interaction.channel, discord.Thread):
            await self._close_thread(interaction.channel, "Denied", approver.display_name)

    @discord.ui.button(label="Thread", style=discord.ButtonStyle.blurple, custom_id="leave_create_thread_btn")
    async def create_thread_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        request_data = find_pending_request(self.request_id)
        if not request_data:
            await interaction.response.send_message("This request no longer exists.", ephemeral=True)
            return

        try:
            requester = await interaction.guild.fetch_member(request_data["member_id"])
        except discord.NotFound:
            await interaction.response.send_message("Could not find the requester.", ephemeral=True)
            return

        # Create thread
        thread = await interaction.channel.create_thread(
            name=f"Leave Discussion - {requester.display_name}",
            type=discord.ChannelType.private_thread,
            invitable=False
        )

        # Add the requester to the private thread
        await thread.add_user(requester)

        # Add the person who created the thread
        await thread.add_user(interaction.user)

        # Post content to thread
        if interaction.message.embeds:
            await thread.send(
                embed=interaction.message.embeds[0],
                view=LeaveApprovalView(request_id=self.request_id)
            )
        else:
            await thread.send(
                f"Leave discussion for {requester.mention}",
                view=LeaveApprovalView(request_id=self.request_id)
            )

        await thread.send(f"Hey {requester.mention}, {interaction.user.mention} started this discussion thread.")
        await interaction.response.send_message("Thread created with approval buttons.", ephemeral=True)


# Helper function to check if user has sufficient level for auto-approval
def has_auto_approval_privilege(user_roles):
    """Check if user gets auto-approval (Core Members only)"""
    for role in user_roles:
        if role.name == "Core Member":
            return True
    return False
