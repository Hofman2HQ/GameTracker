using SQLite;
using System;
using System.ComponentModel.DataAnnotations;
using System.Collections.Generic;
using System.Linq;

namespace MyGameCatalog.Models
{
    public class Game
    {
        [PrimaryKey]
        public int GameId { get; set; }

        [Required]
        [MaxLength(200)]
        public string Title { get; set; }

        [MaxLength(500)]
        public string CoverArtUrl { get; set; }

        [MaxLength(5000)]
        public string Description { get; set; }

        public DateTime? ReleaseDate { get; set; }

        [MaxLength(100)]
        public string Developer { get; set; }

        [MaxLength(100)]
        public string Publisher { get; set; }

        [MaxLength(50)]
        public string Genre { get; set; }

        [MaxLength(50)]
        public string Platform { get; set; }

        [MaxLength(20)]
        public string ESRBRating { get; set; }

        public double? MetacriticScore { get; set; }

        public bool IsMultiplayer { get; set; }

        public DateTime LastUpdated { get; set; }

        [MaxLength(500)]
        public string WebsiteUrl { get; set; }

        [MaxLength(500)]
        public string StoreUrl { get; set; }

        public decimal? Price { get; set; }

        [MaxLength(10)]
        public string Currency { get; set; }

        public bool IsFreeToPlay { get; set; }

        public bool HasDemo { get; set; }

        [MaxLength(50)]
        public string AgeRating { get; set; }

        public int? AveragePlaytime { get; set; }

        public Game()
        {
            LastUpdated = DateTime.UtcNow;
            Currency = "USD";
            IsFreeToPlay = false;
            HasDemo = false;
        }

        public bool Validate(out string error)
        {
            error = null;

            if (string.IsNullOrWhiteSpace(Title))
            {
                error = "Title is required";
                return false;
            }

            if (Title.Length > 200)
            {
                error = "Title is too long (max 200 characters)";
                return false;
            }

            if (CoverArtUrl?.Length > 500)
            {
                error = "Cover art URL is too long (max 500 characters)";
                return false;
            }

            if (Description?.Length > 5000)
            {
                error = "Description is too long (max 5000 characters)";
                return false;
            }

            if (Developer?.Length > 100)
            {
                error = "Developer name is too long (max 100 characters)";
                return false;
            }

            if (Publisher?.Length > 100)
            {
                error = "Publisher name is too long (max 100 characters)";
                return false;
            }

            if (Genre?.Length > 50)
            {
                error = "Genre is too long (max 50 characters)";
                return false;
            }

            if (Platform?.Length > 50)
            {
                error = "Platform is too long (max 50 characters)";
                return false;
            }

            if (ESRBRating?.Length > 20)
            {
                error = "ESRB rating is too long (max 20 characters)";
                return false;
            }

            if (MetacriticScore.HasValue && (MetacriticScore.Value < 0 || MetacriticScore.Value > 100))
            {
                error = "Metacritic score must be between 0 and 100";
                return false;
            }

            if (WebsiteUrl?.Length > 500)
            {
                error = "Website URL is too long (max 500 characters)";
                return false;
            }

            if (StoreUrl?.Length > 500)
            {
                error = "Store URL is too long (max 500 characters)";
                return false;
            }

            if (Price.HasValue && Price.Value < 0)
            {
                error = "Price cannot be negative";
                return false;
            }

            if (Currency?.Length > 10)
            {
                error = "Currency code is too long (max 10 characters)";
                return false;
            }

            if (AgeRating?.Length > 50)
            {
                error = "Age rating is too long (max 50 characters)";
                return false;
            }

            if (AveragePlaytime.HasValue && AveragePlaytime.Value < 0)
            {
                error = "Average playtime cannot be negative";
                return false;
            }

            return true;
        }

        public static class GameStatus
        {
            public const string Backlog = "Backlog";
            public const string InProgress = "In Progress";
            public const string Completed = "Completed";
            public const string Dropped = "Dropped";
            public const string Wishlist = "Wishlist";
            public const string Preordered = "Preordered";
            public const string OnHold = "On Hold";

            public static readonly IReadOnlyList<string> AllStatuses = new[]
            {
                Backlog,
                InProgress,
                Completed,
                Dropped,
                Wishlist,
                Preordered,
                OnHold
            };

            public static bool IsValidStatus(string status)
            {
                return AllStatuses.Contains(status);
            }
        }

        public static class ESRBRatings
        {
            public const string Everyone = "E";
            public const string Everyone10Plus = "E10+";
            public const string Teen = "T";
            public const string Mature = "M";
            public const string AdultsOnly = "AO";
            public const string RatingPending = "RP";

            public static readonly IReadOnlyList<string> AllRatings = new[]
            {
                Everyone,
                Everyone10Plus,
                Teen,
                Mature,
                AdultsOnly,
                RatingPending
            };

            public static bool IsValidRating(string rating)
            {
                return AllRatings.Contains(rating);
            }
        }

        public void UpdateLastUpdated()
        {
            LastUpdated = DateTime.UtcNow;
        }

        public void SetPrice(decimal? price, string currency = "USD")
        {
            if (price.HasValue && price.Value < 0)
            {
                throw new ArgumentException("Price cannot be negative", nameof(price));
            }

            Price = price;
            Currency = currency ?? "USD";
            IsFreeToPlay = !price.HasValue || price.Value == 0;
            UpdateLastUpdated();
        }

        public void SetAgeRating(string rating)
        {
            if (!string.IsNullOrEmpty(rating) && !ESRBRatings.IsValidRating(rating))
            {
                throw new ArgumentException("Invalid ESRB rating", nameof(rating));
            }

            ESRBRating = rating;
            UpdateLastUpdated();
        }
    }
}
