using SQLite;
using System;
using System.ComponentModel.DataAnnotations;
using System.Collections.Generic;
using System.Linq;

namespace MyGameCatalog.Models
{
    public class User
    {
        [PrimaryKey, AutoIncrement]
        public int Id { get; set; }
        
        [Required]
        [EmailAddress]
        [MaxLength(100)]
        [Unique]
        public string Email { get; set; }

        [Required]
        [MaxLength(50)]
        public string Username { get; set; }

        [MaxLength(100)]
        public string DisplayName { get; set; }

        [MaxLength(500)]
        public string ProfilePictureUrl { get; set; }

        public DateTime CreatedAt { get; set; }

        public DateTime LastLoginAt { get; set; }

        public bool IsActive { get; set; }

        [MaxLength(20)]
        public string PreferredLanguage { get; set; }

        [MaxLength(50)]
        public string TimeZone { get; set; }

        public User()
        {
            CreatedAt = DateTime.UtcNow;
            LastLoginAt = DateTime.UtcNow;
            IsActive = true;
            PreferredLanguage = "en-US";
            TimeZone = "UTC";
        }

        public bool Validate(out string error)
        {
            error = null;

            if (string.IsNullOrWhiteSpace(Email))
            {
                error = "Email is required";
                return false;
            }

            if (!new EmailAddressAttribute().IsValid(Email))
            {
                error = "Invalid email format";
                return false;
            }

            if (Email.Length > 100)
            {
                error = "Email is too long (max 100 characters)";
                return false;
            }

            if (string.IsNullOrWhiteSpace(Username))
            {
                error = "Username is required";
                return false;
            }

            if (Username.Length > 50)
            {
                error = "Username is too long (max 50 characters)";
                return false;
            }

            if (DisplayName?.Length > 100)
            {
                error = "Display name is too long (max 100 characters)";
                return false;
            }

            if (ProfilePictureUrl?.Length > 500)
            {
                error = "Profile picture URL is too long (max 500 characters)";
                return false;
            }

            if (PreferredLanguage?.Length > 20)
            {
                error = "Preferred language is too long (max 20 characters)";
                return false;
            }

            if (TimeZone?.Length > 50)
            {
                error = "Time zone is too long (max 50 characters)";
                return false;
            }

            return true;
        }

        public void UpdateLastLogin()
        {
            LastLoginAt = DateTime.UtcNow;
        }

        public void Deactivate()
        {
            IsActive = false;
        }

        public void Activate()
        {
            IsActive = true;
            LastLoginAt = DateTime.UtcNow;
        }
    }
}