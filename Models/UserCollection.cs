using SQLite;
using System;
using System.ComponentModel.DataAnnotations;

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
        public string Status { get; set; }  // e.g., "Backlog", "In Progress", etc.

        [Range(0, 10, ErrorMessage = "Rating must be between 0 and 10")]
        public int? Rating { get; set; }

        [MaxLength(1000)]
        public string Notes { get; set; }

        [Required]
        public DateTime DateAdded { get; set; }

        public UserCollection()
        {
            DateAdded = DateTime.UtcNow;
            Status = "Backlog"; // Default status
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

            return true;
        }
    }
}
