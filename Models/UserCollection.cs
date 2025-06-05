using SQLite;
using System;
using System.ComponentModel.DataAnnotations;
using System.Collections.Generic;
using System.Linq;

namespace MyGameCatalog.Models
{
    public class UserCollection
    {
        [PrimaryKey, AutoIncrement]
        public int Id { get; set; }
        
        [Required]
        [Range(1, int.MaxValue, ErrorMessage = "Invalid User ID")]
        public int UserId { get; set; }

        [Required]
        [Range(1, int.MaxValue, ErrorMessage = "Invalid Game ID")]
        public int GameId { get; set; }

        [Required]
        [MaxLength(50)]
        public string Status { get; set; }

        [Range(0, 10, ErrorMessage = "Rating must be between 0 and 10")]
        public int? Rating { get; set; }

        [MaxLength(1000)]
        public string Notes { get; set; }

        [Required]
        public DateTime DateAdded { get; set; }

        public DateTime? DateStarted { get; set; }

        public DateTime? DateCompleted { get; set; }

        public int? PlayTimeHours { get; set; }

        public bool IsFavorite { get; set; }

        public DateTime LastModified { get; set; }

        [MaxLength(50)]
        public string Platform { get; set; }

        [MaxLength(50)]
        public string Edition { get; set; }

        [MaxLength(50)]
        public string PlaythroughStatus { get; set; }

        public int? CompletionPercentage { get; set; }

        public bool IsHidden { get; set; }

        [MaxLength(50)]
        public string CustomStatus { get; set; }

        public List<string> Tags { get; set; }

        public UserCollection()
        {
            DateAdded = DateTime.UtcNow;
            LastModified = DateTime.UtcNow;
            Status = Game.GameStatus.Backlog;
            IsFavorite = false;
            IsHidden = false;
            Tags = new List<string>();
        }

        public bool Validate(out string error)
        {
            error = null;
            
            if (UserId <= 0)
            {
                error = "Invalid User ID";
                return false;
            }
            
            if (GameId <= 0)
            {
                error = "Invalid Game ID";
                return false;
            }
            
            if (string.IsNullOrEmpty(Status))
            {
                error = "Status is required";
                return false;
            }
            
            if (Status.Length > 50)
            {
                error = "Status is too long (max 50 characters)";
                return false;
            }

            if (!Game.GameStatus.IsValidStatus(Status))
            {
                error = "Invalid game status";
                return false;
            }
            
            if (Rating.HasValue && (Rating.Value < 0 || Rating.Value > 10))
            {
                error = "Rating must be between 0 and 10";
                return false;
            }
            
            if (Notes?.Length > 1000)
            {
                error = "Notes are too long (max 1000 characters)";
                return false;
            }

            if (PlayTimeHours.HasValue && PlayTimeHours.Value < 0)
            {
                error = "Play time cannot be negative";
                return false;
            }

            if (Platform?.Length > 50)
            {
                error = "Platform is too long (max 50 characters)";
                return false;
            }

            if (Edition?.Length > 50)
            {
                error = "Edition is too long (max 50 characters)";
                return false;
            }

            if (PlaythroughStatus?.Length > 50)
            {
                error = "Playthrough status is too long (max 50 characters)";
                return false;
            }

            if (CompletionPercentage.HasValue && (CompletionPercentage.Value < 0 || CompletionPercentage.Value > 100))
            {
                error = "Completion percentage must be between 0 and 100";
                return false;
            }

            if (CustomStatus?.Length > 50)
            {
                error = "Custom status is too long (max 50 characters)";
                return false;
            }

            if (DateStarted.HasValue && DateCompleted.HasValue && DateStarted.Value > DateCompleted.Value)
            {
                error = "Start date cannot be after completion date";
                return false;
            }

            return true;
        }

        public void UpdateStatus(string newStatus)
        {
            if (!Game.GameStatus.IsValidStatus(newStatus))
            {
                throw new ArgumentException("Invalid game status", nameof(newStatus));
            }

            Status = newStatus;
            LastModified = DateTime.UtcNow;

            switch (newStatus)
            {
                case Game.GameStatus.InProgress:
                    DateStarted ??= DateTime.UtcNow;
                    break;
                case Game.GameStatus.Completed:
                    DateCompleted ??= DateTime.UtcNow;
                    CompletionPercentage = 100;
                    break;
            }
        }

        public void UpdateRating(int? newRating)
        {
            if (newRating.HasValue && (newRating.Value < 0 || newRating.Value > 10))
            {
                throw new ArgumentException("Rating must be between 0 and 10", nameof(newRating));
            }

            Rating = newRating;
            LastModified = DateTime.UtcNow;
        }

        public void UpdatePlayTime(int? hours)
        {
            if (hours.HasValue && hours.Value < 0)
            {
                throw new ArgumentException("Play time cannot be negative", nameof(hours));
            }

            PlayTimeHours = hours;
            LastModified = DateTime.UtcNow;
        }

        public void ToggleFavorite()
        {
            IsFavorite = !IsFavorite;
            LastModified = DateTime.UtcNow;
        }

        public void UpdateCompletionPercentage(int? percentage)
        {
            if (percentage.HasValue && (percentage.Value < 0 || percentage.Value > 100))
            {
                throw new ArgumentException("Completion percentage must be between 0 and 100", nameof(percentage));
            }

            CompletionPercentage = percentage;
            LastModified = DateTime.UtcNow;

            if (percentage == 100)
            {
                Status = Game.GameStatus.Completed;
                DateCompleted ??= DateTime.UtcNow;
            }
        }

        public void AddTag(string tag)
        {
            if (string.IsNullOrWhiteSpace(tag))
            {
                throw new ArgumentException("Tag cannot be empty", nameof(tag));
            }

            if (!Tags.Contains(tag))
            {
                Tags.Add(tag);
                LastModified = DateTime.UtcNow;
            }
        }

        public void RemoveTag(string tag)
        {
            if (Tags.Remove(tag))
            {
                LastModified = DateTime.UtcNow;
            }
        }

        public void SetCustomStatus(string status)
        {
            if (status?.Length > 50)
            {
                throw new ArgumentException("Custom status is too long (max 50 characters)", nameof(status));
            }

            CustomStatus = status;
            LastModified = DateTime.UtcNow;
        }

        public void ToggleHidden()
        {
            IsHidden = !IsHidden;
            LastModified = DateTime.UtcNow;
        }
    }
}
