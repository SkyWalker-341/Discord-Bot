import discord
import json
import os
from typing import Set, List, Optional
from datetime import datetime, timedelta

CURRENT_TEAM_CACHE_FILE = "data/current_team_cache.json"
CURRENT_TEAM_ROLE_NAME = "current-team"  

class CurrentTeamManager:
    """
    Centralized manager for current-team role filtering.
    Handles caching, validation, and provides decorators for easy integration.
    """
    
    def __init__(self):
        self._cache = {}  # guild_id -> {user_ids: set, last_updated: datetime}
        self._cache_duration = timedelta(minutes=30)  # Cache for 30 minutes
        self.load_cache()
    
    def load_cache(self):
        """Load cached current-team members from file."""
        if os.path.exists(CURRENT_TEAM_CACHE_FILE):
            try:
                with open(CURRENT_TEAM_CACHE_FILE, "r") as f:
                    data = json.load(f)
                    for guild_id, cache_data in data.items():
                        self._cache[int(guild_id)] = {
                            "user_ids": set(cache_data["user_ids"]),
                            "last_updated": datetime.fromisoformat(cache_data["last_updated"])
                        }
            except Exception as e:
                print(f"Error loading current-team cache: {e}")
                self._cache = {}
    
    def save_cache(self):
        """Save current-team cache to file."""
        try:
            os.makedirs(os.path.dirname(CURRENT_TEAM_CACHE_FILE), exist_ok=True)
            data = {}
            for guild_id, cache_data in self._cache.items():
                data[str(guild_id)] = {
                    "user_ids": list(cache_data["user_ids"]),
                    "last_updated": cache_data["last_updated"].isoformat()
                }
            with open(CURRENT_TEAM_CACHE_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving current-team cache: {e}")
    
    def _is_cache_valid(self, guild_id: int) -> bool:
        """Check if cache is still valid for a guild."""
        if guild_id not in self._cache:
            return False
        last_updated = self._cache[guild_id]["last_updated"]
        return datetime.now() - last_updated < self._cache_duration
    
    def _update_cache(self, guild: discord.Guild) -> Set[int]:
        """Update cache for a specific guild."""
        current_team_ids = set()
        
        for member in guild.members:
            if member.bot:
                continue
            if self._has_current_team_role(member.roles):
                current_team_ids.add(member.id)
        
        self._cache[guild.id] = {
            "user_ids": current_team_ids,
            "last_updated": datetime.now()
        }
        
        # Save to file asynchronously (or you can make this async)
        self.save_cache()
        
        print(f"Updated current-team cache for {guild.name}: {len(current_team_ids)} members")
        return current_team_ids
    
    def _has_current_team_role(self, roles: List[discord.Role]) -> bool:
        """Check if roles contain current-team role."""
        return any(role.name.lower() == CURRENT_TEAM_ROLE_NAME.lower() for role in roles)
    
    def is_current_team_member(self, member: discord.Member) -> bool:
        """
        Main method to check if a member is in current-team.
        Uses cache when possible, updates when necessary.
        """
        if member.bot:
            return False
        
        guild_id = member.guild.id
        
        # Check cache first
        if self._is_cache_valid(guild_id):
            return member.id in self._cache[guild_id]["user_ids"]
        
        # Cache is invalid, refresh it
        current_team_ids = self._update_cache(member.guild)
        return member.id in current_team_ids
    
    def get_current_team_members(self, guild: discord.Guild, force_refresh: bool = False) -> List[discord.Member]:
        """
        Get all current-team members for a guild.
        Returns list of Member objects.
        """
        guild_id = guild.id
        
        # Refresh cache if forced or invalid
        if force_refresh or not self._is_cache_valid(guild_id):
            self._update_cache(guild)
        
        current_team_ids = self._cache.get(guild_id, {}).get("user_ids", set())
        
        # Convert IDs back to Member objects
        current_team_members = []
        for member in guild.members:
            if member.id in current_team_ids:
                current_team_members.append(member)
        
        return current_team_members
    
    def get_current_team_count(self, guild: discord.Guild) -> int:
        """Get count of current-team members."""
        guild_id = guild.id
        if not self._is_cache_valid(guild_id):
            self._update_cache(guild)
        return len(self._cache.get(guild_id, {}).get("user_ids", set()))
    
    def force_refresh_cache(self, guild: discord.Guild):
        """Force refresh the cache for a guild (useful after role changes)."""
        self._update_cache(guild)
    
    def remove_member_from_cache(self, guild_id: int, user_id: int):
        """Remove a specific member from cache (useful for immediate updates)."""
        if guild_id in self._cache:
            self._cache[guild_id]["user_ids"].discard(user_id)
            self.save_cache()
    
    def add_member_to_cache(self, guild_id: int, user_id: int):
        """Add a specific member to cache (useful for immediate updates)."""
        if guild_id in self._cache:
            self._cache[guild_id]["user_ids"].add(user_id)
            self.save_cache()

# Global instance
current_team_manager = CurrentTeamManager()

# Decorator functions for easy integration
def current_team_only(func):
    """
    Decorator that ensures only current-team members can execute the function.
    For use with Discord interaction functions.
    """
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        if not current_team_manager.is_current_team_member(interaction.user):
            await interaction.response.send_message(
                "Access denied. This bot only monitors members with the 'current-team' role.",
                ephemeral=True
            )
            return
        return await func(interaction, *args, **kwargs)
    return wrapper

def filter_current_team_members(members: List[discord.Member]) -> List[discord.Member]:
    """Filter a list of members to only include current-team members."""
    return [member for member in members if current_team_manager.is_current_team_member(member)]
